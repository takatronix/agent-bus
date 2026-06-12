from __future__ import annotations

import json
import logging
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import load_settings
from .discord import DiscordNotifier, EVENT_SEVERITY
from .store import Store

LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class AgentBusHandler(BaseHTTPRequestHandler):
    server: "AgentBusHTTPServer"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            if not self._authorized():
                raise ApiError(HTTPStatus.UNAUTHORIZED, "missing or invalid Agent Bus token")
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            body = self._read_json() if method == "POST" else {}

            if method == "GET" and path == "/healthz":
                self._send({"ok": True, "service": "agent-bus"})
                return
            if method == "GET" and path == "/tasks":
                self._send(
                    {
                        "tasks": self.server.store.list_tasks(
                            status=_one(query, "status"),
                            project=_one(query, "project"),
                            owner=_one(query, "owner"),
                            target_agent=_one(query, "target_agent"),
                            limit=_int(query, "limit", 50),
                        )
                    }
                )
                return
            if method == "POST" and path == "/tasks":
                task = self.server.store.create_task(body)
                self.server.notifier.notify_task(task, "task_created")
                self._send({"task": task}, HTTPStatus.CREATED)
                return
            if method == "GET" and path.startswith("/tasks/"):
                self._send({"task": self.server.store.get_task(path.split("/", 2)[2])})
                return
            if method == "POST" and path.startswith("/tasks/") and path.endswith("/claim"):
                task_id = path.split("/")[2]
                agent = body.get("agent") or body.get("actor")
                if not agent:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "agent is required")
                task = self.server.store.claim_task(task_id, agent)
                event = self.server.store.create_event(
                    {
                        "task_id": task_id,
                        "type": "task_claimed",
                        "actor": agent,
                        "body": f"{agent} claimed {task_id}",
                    }
                )
                self.server.notifier.notify_event(event, task)
                self._send({"task": task, "event": event})
                return
            if method == "POST" and path.startswith("/tasks/") and path.endswith("/update"):
                task_id = path.split("/")[2]
                task = self.server.store.update_task(task_id, body)
                actor = body.get("actor") or body.get("owner") or task.get("owner") or "agent-bus"
                event_type = body.get("event_type") or task.get("status") or "task_updated"
                event = self.server.store.create_event(
                    {
                        "task_id": task_id,
                        "type": event_type,
                        "actor": actor,
                        "body": body.get("note", ""),
                        "severity": EVENT_SEVERITY.get(event_type, "info"),
                    }
                )
                self.server.notifier.notify_event(event, task)
                self._send({"task": task, "event": event})
                return
            if method == "GET" and path == "/events":
                self._send(
                    {
                        "events": self.server.store.list_events(
                            task_id=_one(query, "task_id"),
                            limit=_int(query, "limit", 50),
                        )
                    }
                )
                return
            if method == "POST" and path == "/events":
                event = self.server.store.create_event(body)
                task = None
                if event.get("task_id"):
                    try:
                        task = self.server.store.get_task(event["task_id"])
                    except KeyError:
                        task = None
                self.server.notifier.notify_event(event, task)
                self._send({"event": event}, HTTPStatus.CREATED)
                return
            if method == "GET" and path == "/artifacts":
                self._send(
                    {
                        "artifacts": self.server.store.list_artifacts(
                            task_id=_one(query, "task_id"),
                            limit=_int(query, "limit", 50),
                        )
                    }
                )
                return
            if method == "POST" and path == "/artifacts":
                artifact = self.server.store.create_artifact(body)
                if artifact.get("task_id"):
                    event = self.server.store.create_event(
                        {
                            "task_id": artifact["task_id"],
                            "type": "artifact_attached",
                            "actor": body.get("actor", "agent-bus"),
                            "body": artifact.get("summary") or artifact.get("path") or artifact.get("url") or artifact["id"],
                            "refs": [v for v in [artifact.get("path"), artifact.get("url")] if v],
                        }
                    )
                    try:
                        task = self.server.store.get_task(artifact["task_id"])
                    except KeyError:
                        task = None
                    self.server.notifier.notify_event(event, task)
                self._send({"artifact": artifact}, HTTPStatus.CREATED)
                return
            if method == "GET" and path == "/agents":
                self._send({"agents": self.server.store.list_agents()})
                return
            if method == "POST" and path == "/agents/heartbeat":
                if "name" not in body:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "name is required")
                self._send({"agent": self.server.store.heartbeat_agent(body)})
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        except ApiError as exc:
            self._send({"error": exc.message}, exc.status)
        except KeyError as exc:
            self._send({"error": f"not found: {exc.args[0]}"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._send({"error": str(exc)}, HTTPStatus.CONFLICT)
        except Exception as exc:
            LOGGER.exception("request failed")
            self._send({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _authorized(self) -> bool:
        if self.path.startswith("/healthz") or not self.server.token:
            return True
        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-Agent-Bus-Token", "")
        return auth == f"Bearer {self.server.token}" or token == self.server.token

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return value

    def _send(self, value: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class AgentBusHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], store: Store, notifier: DiscordNotifier, token: str | None):
        super().__init__(server_address, AgentBusHandler)
        self.store = store
        self.notifier = notifier
        self.token = token


def _one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _int(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _one(query, key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    store = Store(settings.db_path, settings.artifact_dir)
    notifier = DiscordNotifier(settings.discord_webhook_url, settings.discord_webhook_routes)
    server = AgentBusHTTPServer((settings.host, settings.port), store, notifier, settings.token)
    print(f"agent-bus listening on http://{settings.host}:{settings.port}", file=sys.stderr)
    print(f"db: {settings.db_path}", file=sys.stderr)
    if settings.host != "127.0.0.1" and not settings.token:
        print("warning: AGENT_BUS_TOKEN is empty while binding to a non-local host", file=sys.stderr)
    if notifier.enabled():
        print("discord webhook: enabled", file=sys.stderr)
    else:
        print("discord webhook: disabled", file=sys.stderr)
    server.serve_forever()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
