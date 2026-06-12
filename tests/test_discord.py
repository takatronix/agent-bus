from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_bus.discord import DiscordNotifier


class DiscordNotifierTest(unittest.TestCase):
    def test_routes_by_project_then_repo_then_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes = Path(tmp) / "routes.json"
            routes.write_text(
                json.dumps(
                    {
                        "default": "https://default.example",
                        "projects": {"alpha": "https://alpha.example"},
                        "repos": {"repo-a": "https://repo-a.example"},
                    }
                ),
                encoding="utf-8",
            )
            notifier = DiscordNotifier(None, routes)

            self.assertEqual(
                notifier._webhook_for({}, {"project": "alpha", "repo": "repo-a"}),
                "https://alpha.example",
            )
            self.assertEqual(
                notifier._webhook_for({}, {"project": "beta", "repo": "repo-a"}),
                "https://repo-a.example",
            )
            self.assertEqual(
                notifier._webhook_for({}, {"project": "beta", "repo": "repo-b"}),
                "https://default.example",
            )


if __name__ == "__main__":
    unittest.main()
