from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

import requests

from agent_bus.discord import DiscordNotifier
from agent_bus.server import AgentBusHTTPServer
from agent_bus.store import Store


class ApiTest(unittest.TestCase):
    def test_http_task_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bus.sqlite3", Path(tmp) / "artifacts")
            server = AgentBusHTTPServer(("127.0.0.1", 0), store, DiscordNotifier(None), token=None)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                health = requests.get(f"{base}/healthz", timeout=5)
                self.assertEqual(health.status_code, 200)

                created = requests.post(
                    f"{base}/tasks",
                    json={"title": "Wire agent bus", "body": "Build it", "project": "agent-bus"},
                    timeout=5,
                )
                self.assertEqual(created.status_code, 201)
                task = created.json()["task"]
                self.assertEqual(task["project"], "agent-bus")

                claimed = requests.post(
                    f"{base}/tasks/{task['id']}/claim",
                    json={"agent": "codex-test"},
                    timeout=5,
                )
                self.assertEqual(claimed.status_code, 200)
                self.assertEqual(claimed.json()["task"]["claimed_by"], "codex-test")

                posted = requests.post(
                    f"{base}/events",
                    json={
                        "task_id": task["id"],
                        "type": "progress",
                        "actor": "codex-test",
                        "body": "ok",
                    },
                    timeout=5,
                )
                self.assertEqual(posted.status_code, 201)

                events = requests.get(f"{base}/events?task_id={task['id']}", timeout=5)
                self.assertEqual(events.status_code, 200)
                self.assertGreaterEqual(len(events.json()["events"]), 2)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
