"""Regression checks for reviewed operational failures; isolated real processes/DB."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import agent
import client
import cloudflare_connect
import credentials


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pickle-recovery-")
        self.root = Path(self.temp.name)
        (self.root / "agent-token").write_text("test-" + "a" * 48)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.bridge = None

    def tearDown(self):
        if self.bridge:
            self.bridge.stopping.set()
            self.bridge.worker.join(4)
            self.bridge.db.close()
            os.close(self.bridge.workspace.fd)
        self.temp.cleanup()

    def spec(self, code, timeout=6):
        return {"argv": [sys.executable, "-I", "-c", code], "cwd": str(self.workspace), "timeout_sec": timeout}

    def start(self, tasks=None):
        self.bridge = agent.Bridge({"workspace": str(self.workspace), "tasks": tasks or {}}, self.root)
        return self.bridge

    def finish(self, job):
        for unused in range(100):
            job = self.bridge.get(job["id"])
            if job["state"] in agent.TERMINAL:
                return job
            time.sleep(.03)
        self.fail("worker did not finish")

    def test_closed_streams_do_not_end_process_deadline(self):
        result = agent.run_task(self.spec("import os,time; os.close(1); os.close(2); time.sleep(2.3)"), self.root)
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertFalse((self.root / "active-process.json").exists())

    def test_descendant_pipe_does_not_turn_success_into_timeout(self):
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',\"import time; time.sleep(1); open('escaped.txt','w').write('bad')\"]); print('parent done')"
        result = agent.run_task(self.spec(code, .8), self.root)
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertTrue(result["truncated"])
        self.assertIn("parent done", result["stdout"])
        time.sleep(1.1)
        self.assertFalse((self.workspace / "escaped.txt").exists())

    def test_marker_failure_reaps_child_and_corruption_does_not_block_start(self):
        children = []
        real = subprocess.Popen
        def capture(*args, **kwargs):
            proc = real(*args, **kwargs)
            children.append(proc)
            return proc
        with patch.object(agent.subprocess, "Popen", side_effect=capture), patch.object(agent, "process_signature", side_effect=RuntimeError("probe")):
            with self.assertRaises(RuntimeError):
                agent.run_task(self.spec("import time; time.sleep(30)"), self.root)
        self.assertIsNotNone(children[0].poll())
        marker = self.root / "active-process.json"
        for invalid in ("", "[]", '{"pid":true,"signature":"fake"}'):
            marker.write_text(invalid)
            agent.recover_process(self.root)
            self.assertFalse(marker.exists())
        self.start()
        self.assertTrue(self.bridge.healthy())

    def test_history_compacts_without_replaying_request(self):
        bridge = self.start()
        now = time.time()
        payload = {"request_id": "old-0", "action": "system.status", "args": {}}
        fingerprint = hashlib.sha256(agent.canonical({"action": payload["action"], "args": {}}).encode()).hexdigest()
        with bridge.lock, bridge.db:
            for i in range(agent.MAX_JOBS):
                bridge.db.execute("INSERT INTO jobs (id,request_id,fingerprint,action,args,state,created,updated,result) VALUES (?,?,?,?,?,?,?,?,?)",
                                  (format(i, "032x"), "old-" + str(i), fingerprint, "system.status", "{}", "succeeded", now-3000+i, now-3000+i, '{"old":true}'))
        job, reused = bridge.submit({**payload, "request_id": "after-full"})
        self.assertFalse(reused)
        self.assertEqual(self.finish(job)["state"], "succeeded")
        archived, reused = bridge.submit(payload)
        self.assertTrue(reused)
        self.assertEqual(archived["id"], "0" * 32)
        self.assertTrue(archived["archived"])
        self.assertFalse(archived["result_available"])
        with self.assertRaises(agent.Problem) as error:
            bridge.submit({**payload, "action": "files.list", "args": {"path": "."}})
        self.assertEqual(error.exception.status, 409)
        with bridge.lock, bridge.db:
            self.assertLess(bridge.db.execute("SELECT count(*) FROM jobs WHERE archived=0").fetchone()[0], agent.MAX_JOBS)
            bridge.db.execute("UPDATE jobs SET updated=? WHERE id=?", (now-31*86400, "0"*32))
        bridge.submit({**payload, "request_id": "expire-receipt"})
        with bridge.lock:
            self.assertIsNone(bridge.db.execute("SELECT id FROM jobs WHERE id=?", ("0"*32,)).fetchone())

    def test_daily_limit_is_not_consumed_by_retry_and_json_is_typed(self):
        bridge = self.start({"summary": {**self.spec('print(\'{"summary":"ok"}\')'), "daily_limit": 1, "output_format": "json"}})
        payload = {"request_id": "once", "action": "task.run", "args": {"task": "summary"}}
        job, unused = bridge.submit(payload)
        job = self.finish(job)
        self.assertEqual(job["result"]["parsed"]["summary"], "ok")
        again, reused = bridge.submit(payload)
        self.assertTrue(reused)
        self.assertEqual(job["id"], again["id"])
        with self.assertRaises(agent.Problem) as error:
            bridge.submit({**payload, "request_id": "twice"})
        self.assertEqual(error.exception.code, "daily_task_limit")
        with bridge.lock:
            self.assertEqual(bridge.db.execute("SELECT count FROM task_usage").fetchone()[0], 1)

    def test_worker_database_error_is_visible_and_rejects_new_work(self):
        bridge = self.start()
        with bridge.lock, bridge.db:
            bridge.db.execute("CREATE TRIGGER fail_running BEFORE UPDATE OF state ON jobs WHEN NEW.state='running' BEGIN SELECT RAISE(FAIL,'injected storage error'); END")
        bridge.submit({"request_id": "fault", "action": "system.status", "args": {}})
        for unused in range(100):
            if bridge.worker_error:
                break
            time.sleep(.02)
        self.assertFalse(bridge.healthy())
        self.assertFalse(bridge.worker.is_alive())
        with self.assertRaises(agent.Problem) as error:
            bridge.submit({"request_id": "after-fault", "action": "system.status", "args": {}})
        self.assertEqual(error.exception.status, 503)
        server = agent.Server(("127.0.0.1", 0), bridge)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            code, body = client.request({"url": "http://127.0.0.1:" + str(server.server_port), "token": bridge.token}, "GET", "/health")
            self.assertEqual(code, 503)
            self.assertEqual(body["status"], "degraded")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_client_preserves_pending_and_network_error_receipts(self):
        pending = {"job": {"id": "a" * 32, "state": "running", "request_id": "same"}}
        with patch.object(client, "request", return_value=(200, pending)):
            code, body = client.wait({}, "a"*32, 0)
        self.assertEqual(body["job"]["state"], "running")
        self.assertTrue(body["waiting_timed_out"])
        self.assertEqual(client.exit_status(code, body), 2)
        with patch.object(client, "request", side_effect=OSError("offline")):
            code, body = client.wait({}, "b"*32)
        self.assertEqual(body["job"]["id"], "b"*32)
        self.assertEqual(client.exit_status(code, body), 2)
        self.assertEqual(client.exit_status(200, {"job": {"state": "succeeded", "archived": True}}), 3)

    def test_token_renewal_preserves_secret_and_scope(self):
        setup = object.__new__(cloudflare_connect.Setup)
        setup.account = "/accounts/test-only"
        setup.state = {"service_token_id": "owned-id"}
        local = {"id": "owned-id", "client_id": "same-client", "client_secret": "test-only-secret", "name": "owned-name"}
        (self.root / "service-token.json").write_text(json.dumps(local))
        remote = {k: v for k, v in local.items() if k != "client_secret"}
        remote["expires_at"] = "2030-01-01T00:00:00Z"
        with patch.object(cloudflare_connect, "STORE", self.root), patch.object(cloudflare_connect, "RUNTIME", self.root), \
                patch.object(setup, "api", return_value=remote) as api, \
                patch.object(setup, "preserve_app", return_value=True) as preserve, \
                patch.object(setup, "verify_policy", return_value=True):
            setup.renew()
        mutations = [call for call in api.call_args_list if len(call.args) > 1]
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].args, ("/accounts/test-only/access/service_tokens/owned-id", "PUT", {"name": "owned-name", "duration": "720h"}))
        self.assertEqual(json.loads((self.root / "service-token.json").read_text())["client_secret"], "test-only-secret")
        self.assertEqual(preserve.call_count, 2)
        self.assertEqual(credentials.expiry_status("2020-01-01T00:00:00Z")["status"], "expired")


if __name__ == "__main__":
    unittest.main(verbosity=2)
