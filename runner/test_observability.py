"""State/event regression tests with real SQLite, HTTP, restart and child processes."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import agent
import client


class ObservabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pickle-observe-")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.root / "agent-token").write_text("test-only-" + "x"*48)
        self.config = {"workspace": str(self.workspace), "tasks": {
            "slow": {"argv": [sys.executable, "-I", "-c", "import time; time.sleep(.8); print('private-output')"],
                     "cwd": str(self.workspace), "timeout_sec": 3}}}
        self.bridge = agent.Bridge(self.config, self.root)

    def close_bridge(self):
        self.bridge.stopping.set()
        self.bridge.worker.join(4)
        self.bridge.db.close()
        os.close(self.bridge.workspace.fd)

    def tearDown(self):
        self.close_bridge()
        self.temp.cleanup()

    def finish(self, job):
        for unused in range(160):
            current = self.bridge.get(job["id"])
            if current["state"] in agent.TERMINAL:
                return current
            time.sleep(.025)
        self.fail("job did not finish")

    def submit(self, key, action="system.status", args=None):
        return self.bridge.submit({"request_id": key, "action": action, "args": args or {}})

    def test_lifecycle_retry_and_private_body_stays_out_of_feed(self):
        args = {"path": "private.md", "content": "SECRET-PROMPT-BODY", "expected_sha256": None}
        job, unused = self.submit("life", "files.write", args)
        self.finish(job)
        feed = self.bridge.events()
        self.assertEqual([e["type"] for e in feed["events"]], ["job.queued", "job.running", "job.succeeded"])
        self.assertNotIn("SECRET-PROMPT-BODY", json.dumps(feed))
        before = feed["next_cursor"]
        same, reused = self.submit("life", "files.write", args)
        self.assertTrue(reused)
        self.assertEqual(same["id"], job["id"])
        self.assertEqual(self.bridge.events(before)["events"], [])
        state = self.bridge.state()
        self.assertFalse(state["needs_attention"])
        self.assertFalse(state["progress_known"])
        self.assertEqual(state["recent"][0]["business_acceptance"], "not_configured")
        self.assertNotIn("SECRET-PROMPT-BODY", json.dumps(state))

    def test_pagination_expired_cursor_and_bounded_history(self):
        self.finish(self.submit("page-one")[0])
        self.finish(self.submit("page-two")[0])
        first = self.bridge.events(0, 2)
        self.assertTrue(first["has_more"])
        second = self.bridge.events(first["next_cursor"], 100)
        self.assertGreater(second["events"][0]["seq"], first["events"][-1]["seq"])
        with patch.object(agent, "MAX_EVENTS", 4), self.bridge.lock, self.bridge.db:
            self.bridge._prune_events()
        with self.assertRaises(agent.Problem) as error:
            self.bridge.events(1)
        self.assertEqual(error.exception.status, 410)
        self.assertTrue(self.bridge.events()["history_truncated"])
        self.assertEqual(len(self.bridge.events()["events"]), 4)
        with self.assertRaises(agent.Problem) as error:
            self.bridge.events(99999)
        self.assertEqual(error.exception.status, 409)

    def test_heartbeat_is_process_observation_not_model_progress(self):
        with patch.object(agent, "HEARTBEAT_SECONDS", .1):
            job = self.submit("beat", "task.run", {"task": "slow"})[0]
            done = self.finish(job)
        self.assertEqual(done["state"], "succeeded")
        feed = self.bridge.events()["events"]
        beats = [e for e in feed if e["type"] == "job.heartbeat"]
        self.assertGreater(len(beats), 0)
        self.assertTrue(all(e["data"]["process_alive"] and not e["data"]["progress_known"] for e in beats))
        self.assertNotIn("private-output", json.dumps(feed))

    def test_stale_observation_is_visible_without_inventing_failure(self):
        job = self.submit("stale", "task.run", {"task": "slow"})[0]
        for unused in range(100):
            if self.bridge.get(job["id"])["state"] == "running":
                break
            time.sleep(.01)
        with self.bridge.lock, self.bridge.db:
            self.bridge.db.execute("UPDATE job_events SET created=? WHERE job_id=?", (time.time()-100, job["id"]))
        state = self.bridge.state()
        self.assertTrue(state["needs_attention"])
        self.assertTrue(state["active"][0]["observation_stale"])
        self.assertEqual(self.bridge.get(job["id"])["state"], "running")
        self.assertEqual(self.finish(job)["state"], "succeeded")

    def test_restart_keeps_identity_and_cursors_and_imports_only_snapshot(self):
        done = self.finish(self.submit("persist")[0])
        device = self.bridge.device_id
        cursor = self.bridge.events()["next_cursor"]
        self.close_bridge()
        with sqlite3.connect(self.root / "jobs.sqlite3") as db:
            # Simulate a pre-event-feed database at the one-time upgrade boundary.
            db.execute("DELETE FROM runner_metadata WHERE key='event_backfill_v1'")
            now = time.time()-500
            db.execute("INSERT INTO jobs (id,request_id,fingerprint,action,args,state,created,updated) VALUES (?,?,?,?,?,?,?,?)",
                       ("a"*32, "legacy-queued", "f"*64, "system.status", "{}", "queued", now, now))
            db.execute("INSERT INTO jobs (id,request_id,fingerprint,action,args,state,created,updated) VALUES (?,?,?,?,?,?,?,?)",
                       ("b"*32, "legacy-done", "f"*64, "system.status", "{}", "succeeded", now, now))
        self.bridge = agent.Bridge(self.config, self.root)
        self.assertEqual(self.bridge.device_id, device)
        self.assertEqual(self.bridge.get(done["id"])["state"], "succeeded")
        self.assertEqual(self.bridge.get("a"*32)["state"], "interrupted")
        new = self.bridge.events(cursor)["events"]
        self.assertEqual([e["type"] for e in new], ["job.interrupted", "job.snapshot"])
        self.assertTrue(new[-1]["data"]["historical_import"])
        imported = next(j for j in self.bridge.state()["recent"] if j["id"] == "b"*32)
        self.assertEqual(imported["last_event_at"], now)
        self.assertGreater(imported["last_recorded_event_at"], now)

    def test_pruned_events_do_not_reappear_as_new_history_on_restart(self):
        self.finish(self.submit("old-receipt")[0])
        cursor = self.bridge.events()["next_cursor"]
        with self.bridge.lock, self.bridge.db:
            self.bridge.db.execute("DELETE FROM job_events")
        self.close_bridge()
        self.bridge = agent.Bridge(self.config, self.root)
        self.assertEqual(self.bridge.events(cursor)["events"], [])
        self.assertTrue(self.bridge.events()["history_truncated"])

    def test_event_write_failure_rolls_back_submission_before_execution(self):
        with self.bridge.lock, self.bridge.db:
            self.bridge.db.execute("CREATE TRIGGER fault BEFORE INSERT ON job_events WHEN NEW.type='job.queued' BEGIN SELECT RAISE(FAIL,'event storage fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.submit("not-accepted")
        with self.bridge.lock:
            self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        self.assertTrue(self.bridge.queue.empty())

    def test_http_routes_authentication_and_strict_cursor_validation(self):
        server = agent.Server(("127.0.0.1", 0), self.bridge)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cfg = {"url": "http://127.0.0.1:"+str(server.server_port), "token": self.bridge.token}
        try:
            for path in ["/v1/state", "/v1/events?since=0&limit=1"]:
                self.assertEqual(client.request(cfg, "GET", path, auth="none")[0], 401)
                self.assertEqual(client.request(cfg, "GET", path)[0], 200)
            for query in ["since=-1", "since=bad", "since=1&since=2", "limit=0", "limit=101", "unknown=3", "since="]:
                self.assertEqual(client.request(cfg, "GET", "/v1/events?"+query)[0], 400, query)
            self.assertEqual(client.request(cfg, "GET", "/v1/state?since=0")[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
