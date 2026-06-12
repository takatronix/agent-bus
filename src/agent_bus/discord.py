from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .util import compact

LOGGER = logging.getLogger(__name__)


COLORS = {
    "info": 0x3498DB,
    "success": 0x2ECC71,
    "warning": 0xF1C40F,
    "error": 0xE74C3C,
    "critical": 0x992D22,
}

EVENT_SEVERITY = {
    "task_created": "info",
    "task_claimed": "info",
    "progress": "info",
    "blocked": "warning",
    "review_requested": "warning",
    "completed": "success",
    "done": "success",
    "failed": "error",
    "human_required": "critical",
}


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str | None,
        routes_path: str | Path | None = None,
        timeout: float = 10.0,
    ):
        self.default_webhook_url = webhook_url
        self.routes_path = Path(routes_path) if routes_path else None
        self.routes = self._load_routes()
        self.timeout = timeout

    def enabled(self) -> bool:
        return bool(self.default_webhook_url or self.routes.get("projects") or self.routes.get("repos"))

    def notify_event(
        self,
        event: dict[str, Any],
        task: dict[str, Any] | None = None,
        webhook_url: str | None = None,
    ) -> None:
        webhook_url = webhook_url or self._webhook_for(event, task)
        if not webhook_url:
            return
        payload = self._event_payload(event, task)
        self._post(webhook_url, payload)

    def notify_task(
        self,
        task: dict[str, Any],
        event_type: str = "task_created",
        webhook_url: str | None = None,
    ) -> None:
        webhook_url = webhook_url or self._webhook_for({}, task)
        if not webhook_url:
            return
        event = {
            "type": event_type,
            "actor": task.get("created_by") or "agent-bus",
            "body": task.get("body") or task.get("title") or "",
            "severity": EVENT_SEVERITY.get(event_type, "info"),
            "refs": task.get("refs", []),
            "created_at": task.get("created_at"),
        }
        self._post(webhook_url, self._event_payload(event, task))

    def _post(self, webhook_url: str, payload: dict[str, Any]) -> None:
        for attempt in range(3):
            response = requests.post(webhook_url, json=payload, timeout=self.timeout)
            if response.status_code in {200, 204}:
                return
            if response.status_code == 429:
                retry_after = self._retry_after(response)
                time.sleep(min(retry_after, 30.0))
                continue
            if 500 <= response.status_code < 600 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            LOGGER.warning("discord webhook failed: %s %s", response.status_code, response.text[:300])
            return

    def _load_routes(self) -> dict[str, dict[str, str]]:
        routes = {"projects": {}, "repos": {}}
        if not self.routes_path or not self.routes_path.exists():
            return routes
        try:
            raw = json.loads(self.routes_path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.warning("failed to load Discord webhook routes %s: %s", self.routes_path, exc)
            return routes
        if raw.get("default") and not self.default_webhook_url:
            self.default_webhook_url = raw["default"]
        for section in ("projects", "repos"):
            values = raw.get(section) or {}
            if isinstance(values, dict):
                routes[section] = {str(k): str(v) for k, v in values.items() if v}
        return routes

    def _webhook_for(self, event: dict[str, Any], task: dict[str, Any] | None) -> str | None:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        project = (
            (task or {}).get("project")
            or data.get("project")
            or (task or {}).get("metadata", {}).get("project")
        )
        repo = (task or {}).get("repo") or data.get("repo")
        if project and project in self.routes["projects"]:
            return self.routes["projects"][project]
        if repo and repo in self.routes["repos"]:
            return self.routes["repos"][repo]
        return self.default_webhook_url

    def _retry_after(self, response: requests.Response) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        try:
            return float(response.json().get("retry_after", 2.0))
        except Exception:
            return 2.0

    def _event_payload(self, event: dict[str, Any], task: dict[str, Any] | None) -> dict[str, Any]:
        severity = event.get("severity") or EVENT_SEVERITY.get(event.get("type"), "info")
        title = self._title(event, task)
        fields = [
            {"name": "actor", "value": str(event.get("actor") or "unknown")[:1024], "inline": True},
            {"name": "type", "value": str(event.get("type") or "message")[:1024], "inline": True},
        ]
        if task:
            fields.extend(
                [
                    {"name": "task", "value": str(task["id"])[:1024], "inline": True},
                    {"name": "status", "value": str(task.get("status", ""))[:1024], "inline": True},
                ]
            )
            if task.get("project"):
                fields.append({"name": "project", "value": str(task["project"])[:1024], "inline": True})
            if task.get("repo"):
                fields.append({"name": "repo", "value": str(task["repo"])[:1024], "inline": True})
            if task.get("branch"):
                fields.append({"name": "branch", "value": str(task["branch"])[:1024], "inline": True})
        if event.get("refs"):
            fields.append({"name": "refs", "value": compact("\n".join(map(str, event["refs"])), 1024)})
        body = compact(str(event.get("body") or ""), 3500)
        embed = {
            "title": compact(title, 256),
            "description": body or None,
            "color": COLORS.get(severity, COLORS["info"]),
            "fields": fields[:12],
            "timestamp": event.get("created_at"),
        }
        return {
            "username": str(event.get("actor") or "agent-bus")[:80],
            "allowed_mentions": {"parse": []},
            "embeds": [embed],
        }

    def _title(self, event: dict[str, Any], task: dict[str, Any] | None) -> str:
        prefix = f"[{task['id']}]" if task else "[agent-bus]"
        task_title = f" {task['title']}" if task and task.get("title") else ""
        return f"{prefix} {event.get('type', 'message')}{task_title}"
