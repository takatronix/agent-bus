from __future__ import annotations

import logging
import time
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
    def __init__(self, webhook_url: str | None, timeout: float = 10.0):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def notify_event(self, event: dict[str, Any], task: dict[str, Any] | None = None) -> None:
        if not self.webhook_url:
            return
        payload = self._event_payload(event, task)
        self._post(payload)

    def notify_task(self, task: dict[str, Any], event_type: str = "task_created") -> None:
        if not self.webhook_url:
            return
        event = {
            "type": event_type,
            "actor": task.get("created_by") or "agent-bus",
            "body": task.get("body") or task.get("title") or "",
            "severity": EVENT_SEVERITY.get(event_type, "info"),
            "refs": task.get("refs", []),
            "created_at": task.get("created_at"),
        }
        self._post(self._event_payload(event, task))

    def _post(self, payload: dict[str, Any]) -> None:
        assert self.webhook_url is not None
        for attempt in range(3):
            response = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
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
