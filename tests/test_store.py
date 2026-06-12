from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_bus.store import Store


class StoreTest(unittest.TestCase):
    def test_task_event_artifact_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bus.sqlite3", Path(tmp) / "artifacts")
            task = store.create_task(
                {
                    "title": "Fix login",
                    "body": "Investigate refresh token race.",
                    "created_by": "human",
                    "refs": ["file:src/auth.ts"],
                }
            )
            self.assertEqual(task["status"], "open")
            self.assertEqual(task["refs"], ["file:src/auth.ts"])

            claimed = store.claim_task(task["id"], "codex-test")
            self.assertEqual(claimed["status"], "claimed")
            self.assertEqual(claimed["claimed_by"], "codex-test")

            event = store.create_event(
                {
                    "task_id": task["id"],
                    "type": "progress",
                    "actor": "codex-test",
                    "body": "Tests are running.",
                }
            )
            self.assertEqual(event["task_id"], task["id"])
            self.assertEqual(store.list_events(task["id"])[0]["id"], event["id"])

            artifact = store.create_artifact(
                {
                    "task_id": task["id"],
                    "kind": "summary",
                    "summary": "test summary",
                    "content": "# Summary\nok\n",
                }
            )
            self.assertTrue(Path(artifact["path"]).exists())
            self.assertEqual(store.list_artifacts(task["id"])[0]["id"], artifact["id"])

            done = store.update_task(task["id"], {"status": "done"})
            self.assertEqual(done["status"], "done")

    def test_rejects_double_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bus.sqlite3")
            task = store.create_task({"title": "Task"})
            store.claim_task(task["id"], "agent-a")
            with self.assertRaises(RuntimeError):
                store.claim_task(task["id"], "agent-b")


if __name__ == "__main__":
    unittest.main()
