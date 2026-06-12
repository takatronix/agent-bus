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
                    "project": "platform",
                    "created_by": "human",
                    "refs": ["file:src/auth.ts"],
                }
            )
            self.assertEqual(task["status"], "open")
            self.assertEqual(task["project"], "platform")
            self.assertEqual(task["refs"], ["file:src/auth.ts"])
            self.assertEqual(store.list_tasks(project="platform")[0]["id"], task["id"])
            self.assertEqual(store.get_project("platform")["task_count"], 1)

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
            self.assertEqual(event["project"], "platform")
            self.assertEqual(store.list_events(task["id"])[0]["id"], event["id"])
            self.assertEqual(store.list_events(project="platform")[0]["id"], event["id"])

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
            history = store.project_history("platform")
            self.assertEqual(history["project"]["name"], "platform")
            self.assertEqual(history["tasks"][0]["id"], task["id"])

    def test_project_crud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bus.sqlite3")
            project = store.create_project(
                {
                    "name": "agent-bus",
                    "title": "Agent Bus",
                    "description": "Coordination",
                    "discord_webhook_url": "https://discord.example/webhook",
                }
            )
            self.assertEqual(project["name"], "agent-bus")
            self.assertEqual(project["title"], "Agent Bus")
            self.assertTrue(project["has_discord_webhook"])
            self.assertNotIn("discord_webhook_url", project)
            self.assertEqual(store.get_project_discord_webhook("agent-bus"), "https://discord.example/webhook")
            cleared = store.set_project_discord_webhook("agent-bus", None)
            self.assertFalse(cleared["has_discord_webhook"])
            self.assertEqual(store.list_projects()[0]["name"], "agent-bus")

    def test_rejects_double_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "bus.sqlite3")
            task = store.create_task({"title": "Task"})
            store.claim_task(task["id"], "agent-a")
            with self.assertRaises(RuntimeError):
                store.claim_task(task["id"], "agent-b")


if __name__ == "__main__":
    unittest.main()
