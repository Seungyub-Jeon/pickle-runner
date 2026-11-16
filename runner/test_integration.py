#!/usr/bin/env python3
"""Real subprocess + HTTP tests; never touches production credentials/workspace."""
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import check_remote
from client import encrypted_config


class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="pickle-runtime-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.runtime = cls.base / "runtime"
        cls.workspace = cls.base / "workspace"
        cls.runtime.mkdir(mode=0o700)
        cls.workspace.mkdir(mode=0o700)
        cls.token = "test-only-" + "a" * 48
        (cls.runtime / "agent-token").write_text(cls.token)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        def task(code, timeout=10):
            return {"argv": [sys.executable, "-I", "-c", code], "cwd": str(cls.workspace), "timeout_sec": timeout}
        config = {"port": cls.port, "workspace": str(cls.workspace), "terminal_enabled": True, "tasks": {
            "hello": task("print('runtime-ok')"),
            "slow": task("import time; time.sleep(20)"),
            "fail": task("import sys; sys.exit(7)"),
            "environment": task("import os; print(any(k in os.environ for k in ['OPENAI_API_KEY','AGENT_SECRET','PROBE_SECRET']))"),
            "flood": task("import sys; sys.stdout.write('a'*300000); sys.stderr.write('b'*300000)"),
            "timeout": task("import time,subprocess,sys; subprocess.Popen([sys.executable,'-c',\"import time; time.sleep(2); open('orphan.txt','w').write('bad')\"]); time.sleep(20)", .3)}}
        (cls.runtime / "config.json").write_text(json.dumps(config))
        cls.log = open(cls.runtime / "process.log", "ab")
        cls.addClassCleanup(cls.log.close)
        cls.start()

    @classmethod
    def start(cls):
        env = dict(os.environ, PROBE_SECRET="test-never-forwarded")
        cls.proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("agent.py")), "--runtime", str(cls.runtime)], env=env, stdout=cls.log, stderr=cls.log, start_new_session=True)
        cls.addClassCleanup(cls.stop)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if cls.call("GET", "/health")[0] == 200:
                    return
            except OSError:
                pass
            if cls.proc.poll() is not None:
                raise AssertionError((cls.runtime / "process.log").read_text())
            time.sleep(.05)
        raise AssertionError("test runner did not start within 30 seconds; process log:\n" +
                             (cls.runtime / "process.log").read_text()[-8000:])

    @classmethod
    def stop(cls, force=False):
        if cls.proc.poll() is None:
            cls.proc.send_signal(signal.SIGKILL if force else signal.SIGTERM)
            cls.proc.wait(timeout=6)

    @classmethod
    def tearDownClass(cls):
        cls.stop()
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, auth=True, extra=None, raw=None):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + cls.token
        headers.update(extra or {})
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def submit(self, key, action, args):
        code, body = self.call("POST", "/v1/jobs", {"request_id": key, "action": action, "args": args})
        self.assertIn(code, (200, 202), body)
        return body["job"]

    def finish(self, job):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            code, body = self.call("GET", "/v1/jobs/" + job["id"])
            if body["job"]["state"] in ("succeeded", "failed", "interrupted"):
                return body["job"]
            time.sleep(.025)
        self.fail("job did not finish")

    def await_running(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.call("GET", "/v1/jobs/" + job["id"])[1]["job"]["state"]
            if state == "running":
                return
            time.sleep(.02)
        self.fail("job never started")

    def test_20_cancel_running_and_queued_over_http(self):
        running = self.submit("cancel-running", "terminal.run", {"cwd": str(self.workspace), "command": "exec /bin/sleep 20"})
        self.await_running(running)
        queued = self.submit("cancel-queued", "terminal.run", {"cwd": str(self.workspace), "command": "touch should-not-exist.txt"})
        target = "/v1/jobs/" + running["id"] + "/cancel"
        self.assertEqual(self.call("POST", target, {}, auth=False)[0], 401)
        self.assertEqual(self.call("POST", target, {"unexpected": True})[0], 400)
        code, result = self.call("POST", "/v1/jobs/" + queued["id"] + "/cancel", {})
        self.assertEqual(code, 200)
        self.assertEqual(result["job"]["state"], "interrupted")
        # Metadata queries remain available while a long job owns the worker.
        self.assertEqual(self.call("GET", "/v1/state")[0], 200)
        code, result = self.call("POST", target, {})
        self.assertIn(code, (200, 202))
        final = self.finish(running)
        self.assertEqual(final["state"], "interrupted")
        self.assertEqual(final["error"]["code"], "user_cancel")
        self.assertEqual(self.call("POST", target, {})[1]["job"], final)
        self.assertFalse((self.workspace / "should-not-exist.txt").exists())
        next_job = self.finish(self.submit("after-cancel", "system.status", {}))
        self.assertEqual(next_job["state"], "succeeded")

    def test_24_cancel_frees_full_queue(self):
        running = self.submit("capacity-running", "terminal.run", {"cwd": str(self.workspace), "command": "exec /bin/sleep 20"})
        self.await_running(running)
        queued = [self.submit("capacity-%d" % i, "system.status", {}) for i in range(20)]
        self.assertEqual(self.call("POST", "/v1/jobs", {"request_id":"capacity-overflow", "action":"system.status", "args":{}})[0], 429)
        self.assertEqual(self.call("POST", "/v1/jobs/" + queued[0]["id"] + "/cancel", {})[0], 200)
        replacement = self.submit("capacity-replacement", "system.status", {})
        self.call("POST", "/v1/jobs/" + running["id"] + "/cancel", {})
        self.finish(running)
        self.assertEqual(self.finish(replacement)["state"], "succeeded")

    def test_25_cancel_completion_race_keeps_one_terminal_event(self):
        for index, delay in enumerate((0, .02, .15)):
            with self.subTest(delay=delay):
                job = self.submit("cancel-race-%d" % index, "terminal.run", {"cwd":str(self.workspace), "command":"sleep 0.03; printf done"})
                time.sleep(delay)
                code, response = self.call("POST", "/v1/jobs/" + job["id"] + "/cancel", {})
                self.assertIn(code, (200, 202))
                final = self.finish(job)
                self.assertIn(final["state"], ("succeeded", "interrupted"), final)
                if final["state"] == "succeeded":
                    self.assertEqual(final["result"]["stdout"], "done")
                else:
                    self.assertEqual(final["error"]["code"], "user_cancel")
                self.assertEqual(self.call("POST", "/v1/jobs/" + job["id"] + "/cancel", {})[1]["job"], final)
                with sqlite3.connect(str(self.runtime / "jobs.sqlite3")) as db:
                    count = db.execute("SELECT count(*) FROM job_events WHERE job_id=? AND type IN ('job.succeeded','job.failed','job.interrupted')", (job["id"],)).fetchone()[0]
                self.assertEqual(count, 1)

    def test_21_retry_after_cwd_move(self):
        folder = self.base / "retry-cwd"
        folder.mkdir()
        body = {"request_id": "retry-moved", "action": "terminal.run", "args": {"cwd": str(folder), "command": "printf once > result.txt"}}
        job = self.call("POST", "/v1/jobs", body)[1]["job"]
        self.assertEqual(self.finish(job)["state"], "succeeded")
        folder.rename(self.base / "retry-moved")
        code, repeated = self.call("POST", "/v1/jobs", body)
        self.assertEqual(code, 200)
        self.assertTrue(repeated["reused"])
        self.assertEqual(repeated["job"]["id"], job["id"])
        body["args"]["command"] = "printf twice"
        self.assertEqual(self.call("POST", "/v1/jobs", body)[0], 409)
        body["request_id"] = "new-missing-cwd"
        self.assertEqual(self.call("POST", "/v1/jobs", body)[0], 400)

    def test_22_failure_log_excludes_untrusted_values(self):
        marker = "FAKE_SECRET_MUST_NOT_APPEAR"
        self.call("GET", "/health?token=" + marker, auth=False)
        self.call("GET", "/" + marker)
        self.call("POST", "/v1/jobs", {"request_id": marker, "action": marker, "args": {"command": marker}})
        self.call("POST", "/v1/jobs", {"request_id": "bad-cwd-log", "action": "terminal.run", "args": {"cwd": marker, "command": marker}})
        self.call("POST", "/v1/jobs", raw=b"invalid-json-" + marker.encode())
        log = (self.runtime / "access-failures.log").read_text()
        self.assertNotIn(marker, log)
        self.assertNotIn(self.token, log)
        for value in ("unauthorized", "invalid_json", "terminal.run", "invalid_cwd"):
            self.assertIn(value, log)
        self.assertNotIn("unauthorized", (self.runtime / "audit.log").read_text())
        self.assertEqual((self.runtime / "access-failures.log").stat().st_mode & 0o077, 0)

    def test_23_completed_cancel_preserves_result_and_unknown(self):
        final = self.finish(self.submit("cancel-completed", "system.status", {}))
        code, body = self.call("POST", "/v1/jobs/" + final["id"] + "/cancel", {})
        self.assertEqual(code, 200)
        self.assertEqual(body["job"], final)
        self.assertTrue(body["already_finished"])
        self.assertEqual(self.call("POST", "/v1/jobs/" + "0" * 32 + "/cancel", {})[0], 404)

    def test_01_authentication_and_browser(self):
        for path in ("/health", "/v1/capabilities", "/v1/jobs/" + "a" * 32):
            self.assertEqual(self.call("GET", path, auth=False)[0], 401)
        self.assertEqual(self.call("POST", "/v1/jobs", {}, auth=False)[0], 401)
        self.assertEqual(self.call("GET", "/health", extra={"Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.call("GET", "/health", extra={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.call("GET", "/v1/capabilities")[0], 200)
        self.assertEqual(self.call("GET", "/health?token=wrong")[0], 400)

    def test_02_request_validation(self):
        valid = {"request_id": "invalid", "action": "system.status", "args": {}}
        self.assertEqual(self.call("POST", "/v1/jobs", {**valid, "cmd": "uptime"})[0], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", {**valid, "action": "shell.run"})[0], 403)
        self.assertEqual(self.call("POST", "/v1/jobs", {**valid, "action": "task.run", "args": {"task": "hello", "argv": ["sh"]}})[0], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", {**valid, "action": "task.run", "args": {"task": "unregistered"}})[0], 403)
        self.assertEqual(self.call("POST", "/v1/jobs", raw=b'{"action":"a","action":"b"}')[0], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", raw=b'{"args": NaN}')[0], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", raw=b'[]')[0], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", valid, extra={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/v1/jobs", raw=b"a" * 170000)[0], 413)

    def test_03_file_lifecycle_and_conflict(self):
        job = self.finish(self.submit("create-note", "files.write", {"path": "note.md", "content": "첫 기록\n", "expected_sha256": None}))
        self.assertEqual(job["state"], "succeeded")
        self.assertEqual((self.workspace / "note.md").read_text(), "첫 기록\n")
        read = self.finish(self.submit("read-note", "files.read", {"path": "note.md"}))["result"]
        self.assertEqual(read["sha256"], hashlib.sha256("첫 기록\n".encode()).hexdigest())
        changed = self.finish(self.submit("update-note", "files.write", {"path": "note.md", "content": "두 번째\n", "expected_sha256": read["sha256"]}))
        self.assertEqual(changed["state"], "succeeded")
        stale = self.finish(self.submit("stale-note", "files.write", {"path": "note.md", "content": "lost update", "expected_sha256": read["sha256"]}))
        self.assertEqual(stale["error"]["code"], "write_conflict")
        self.assertEqual((self.workspace / "note.md").read_text(), "두 번째\n")
        mode = (self.workspace / "note.md").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_04_paths_and_symlinks(self):
        for path in ("../escape.txt", "/tmp/escape.txt", ".env", "x/.hidden.json", "x/../escape.md", "evil.py", "a\\b.txt"):
            code, body = self.call("POST", "/v1/jobs", {"request_id": "denied", "action": "files.read", "args": {"path": path}})
            self.assertEqual(code, 403, path)
        outside = self.base / "outside.txt"
        outside.write_text("private")
        (self.workspace / "link.txt").symlink_to(outside)
        (self.workspace / "linked-folder").symlink_to(self.base, target_is_directory=True)
        os.link(outside, self.workspace / "hard.txt")
        os.mkfifo(self.workspace / "pipe.txt")
        for path in ("link.txt", "linked-folder/outside.txt", "hard.txt", "pipe.txt"):
            job = self.finish(self.submit("path-" + path.replace("/", "-"), "files.read", {"path": path}))
            self.assertEqual(job["state"], "failed", path)
            self.assertEqual(job["error"]["code"], "path_denied")
        listing = self.finish(self.submit("listing", "files.list", {"path": "."}))["result"]
        self.assertNotIn("link.txt", [e["name"] for e in listing["entries"]])
        self.assertEqual(outside.read_text(), "private")

    def test_05_concurrent_idempotency(self):
        payload = {"request_id": "concurrent-create", "action": "files.write", "args": {"path": "once.txt", "content": "once", "expected_sha256": None}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda unused: self.call("POST", "/v1/jobs", payload), range(8)))
        self.assertTrue(all(code in (200, 202) for code, body in replies))
        self.assertEqual(len({body["job"]["id"] for code, body in replies}), 1)
        self.assertEqual(sum(not body["reused"] for code, body in replies), 1)
        self.assertEqual(self.finish(replies[0][1]["job"])["state"], "succeeded")
        payload["args"]["content"] = "different"
        self.assertEqual(self.call("POST", "/v1/jobs", payload)[0], 409)

    def test_06_task_execution_bounds_and_environment(self):
        for task in ("hello", "fail", "environment", "flood", "timeout"):
            job = self.finish(self.submit("task-" + task, "task.run", {"task": task}))
            if task == "hello":
                self.assertEqual(job["result"]["stdout"].strip(), "runtime-ok")
            elif task == "fail":
                self.assertEqual(job["result"]["exit_code"], 7)
                self.assertEqual(job["state"], "failed")
            elif task == "environment":
                self.assertEqual(job["result"]["stdout"].strip(), "False")
            elif task == "flood":
                self.assertTrue(job["result"]["truncated"])
                self.assertLessEqual(len(job["result"]["stdout"]), 65536)
                self.assertGreater(job["result"]["output"]["stdout"]["omitted_bytes"], 0)
                self.assertLessEqual(len(job["result"]["stderr"]), 65536)
            else:
                self.assertEqual(job["error"]["code"], "task_timeout")
        time.sleep(2.1)
        self.assertFalse((self.workspace / "orphan.txt").exists())

    def test_07_access_checker_rejects_origin_401(self):
        cfg = {"url": "https://runner.example.org", "token": "test", "access_client_id": "test", "access_client_secret": "test"}
        def bypass(config, method, path, auth):
            if auth in ("agent", "full"):
                return 200, {"service": "pickle-runner", "status": "ok"}
            return 401, {"error": {"code": "unauthorized"}}
        with patch.object(check_remote, "request", side_effect=bypass):
            self.assertFalse(check_remote.check(cfg)["passed"])

    def test_08_restart_preserves_completed_and_interrupts_running(self):
        old = self.finish(self.submit("persist-me", "system.status", {}))
        slow = self.submit("interrupt-me", "task.run", {"task": "slow"})
        deadline = time.monotonic() + 3
        marker = self.runtime / "active-process.json"
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(.025)
        self.assertTrue(marker.exists())
        process = json.loads(marker.read_text())
        queued = self.submit("queued-no-replay", "files.write", {"path": "must-not-replay.txt", "content": "bad", "expected_sha256": None})
        type(self).stop(force=True)
        type(self).start()
        for job in (slow, queued):
            code, body = self.call("GET", "/v1/jobs/" + job["id"])
            self.assertEqual(body["job"]["state"], "interrupted")
        self.assertFalse((self.workspace / "must-not-replay.txt").exists())
        self.assertFalse(marker.exists())
        # Matching process identity was recovered; it must no longer be live.
        check = subprocess.run(["/bin/ps", "-p", str(process["pid"]), "-o", "stat="], capture_output=True, text=True)
        self.assertTrue(check.returncode != 0 or check.stdout.strip().startswith("Z"))
        replay = self.submit("persist-me", "system.status", {})
        self.assertEqual(replay["id"], old["id"])
        self.assertEqual(replay["state"], "succeeded")

    def test_09_encrypted_settings_roundtrip_and_private_key_permissions(self):
        key = self.base / "recipient-private.pem"
        public = self.base / "recipient-public.pem"
        cipher = self.base / "settings.enc"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:4096", "-out", str(key)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        expected = {"url": "https://runner.example.org", "token": "test-only-placeholder"}
        payload = json.dumps(expected).encode()
        result = subprocess.run(["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", str(public),
            "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256"], input=payload, capture_output=True, check=True)
        cipher.write_bytes(result.stdout)
        self.assertNotIn(payload, cipher.read_bytes())
        self.assertEqual(encrypted_config(cipher, key), expected)
        key.chmod(0o644)
        with self.assertRaises(ValueError):
            encrypted_config(cipher, key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
