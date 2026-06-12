from __future__ import annotations

import json
import logging
import sys
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if not self._authorized(method, path, query):
                raise ApiError(HTTPStatus.UNAUTHORIZED, "missing or invalid Agent Bus token")
            body = self._read_json() if method == "POST" else {}

            if method == "GET" and path == "/":
                self._send_html(self._projects_html())
                return
            if method == "GET" and path == "/healthz":
                self._send({"ok": True, "service": "agent-bus"})
                return
            if method == "GET" and path == "/projects":
                self._send({"projects": self.server.store.list_projects(limit=_int(query, "limit", 100))})
                return
            if method == "POST" and path == "/projects":
                project = self.server.store.create_project(body)
                self._send({"project": project}, HTTPStatus.CREATED)
                return
            if method == "GET" and path.startswith("/projects/") and path.endswith("/history"):
                name = unquote(path.split("/")[2])
                self._send(self.server.store.project_history(name, limit=_int(query, "limit", 100)))
                return
            if method == "GET" and path.startswith("/projects/"):
                name = unquote(path.split("/", 2)[2])
                accept = self.headers.get("Accept", "")
                if "text/html" in accept or not accept:
                    self._send_html(self._project_html(name, limit=_int(query, "limit", 100)))
                else:
                    self._send({"project": self.server.store.get_project(name)})
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
                            project=_one(query, "project"),
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

    def _authorized(self, method: str, path: str, query: dict[str, list[str]]) -> bool:
        if path == "/healthz":
            return True
        if method == "GET" and self.server.public_read:
            return True
        if method == "GET" and not self.server.token and not self.server.read_token:
            return True
        if method != "GET" and not self.server.token:
            return True
        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-Agent-Bus-Token", "")
        query_token = _one(query, "token") or _one(query, "read_token")
        valid_tokens = [value for value in [self.server.token, self.server.read_token] if value]
        if method != "GET":
            valid_tokens = [self.server.token] if self.server.token else []
        return any(auth == f"Bearer {value}" or token == value or query_token == value for value in valid_tokens)

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

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        raw = html.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _projects_html(self) -> str:
        projects = self.server.store.list_projects(limit=200)
        recent_events = self.server.store.list_events(limit=30)
        cards = "\n".join(
            f"""
            <a class="card" href="/projects/{escape(project['name'])}">
              <span class="name">{escape(project['title'])}</span>
              <span class="meta">{escape(project['name'])} · {project['active_task_count']} active / {project['task_count']} total</span>
              <span class="desc">{escape(project.get('description') or '')}</span>
            </a>
            """
            for project in projects
        )
        return _page(
            "Agent Bus",
            f"""
            <header><h1>Agent Bus</h1><p>Projects and recent agent activity.</p></header>
            <section class="grid">{cards or '<p class="empty">No projects yet.</p>'}</section>
            <section><h2>Recent Events</h2>{_events_table(recent_events)}</section>
            """,
        )

    def _project_html(self, name: str, limit: int = 100) -> str:
        history = self.server.store.project_history(name, limit=limit)
        project = history["project"]
        return _page(
            project["title"],
            f"""
            <header>
              <a class="back" href="/">&larr; Projects</a>
              <h1>{escape(project['title'])}</h1>
              <p>{escape(project.get('description') or project['name'])}</p>
            </header>
            <section><h2>Tasks</h2>{_tasks_table(history['tasks'])}</section>
            <section><h2>History</h2>{_events_table(history['events'])}</section>
            """,
        )


class AgentBusHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        store: Store,
        notifier: DiscordNotifier,
        token: str | None,
        read_token: str | None = None,
        public_read: bool = False,
    ):
        super().__init__(server_address, AgentBusHandler)
        self.store = store
        self.notifier = notifier
        self.token = token
        self.read_token = read_token
        self.public_read = public_read


def _one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _int(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _one(query, key)
    if not value:
        return default


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      margin: 0;
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: Canvas;
      color: CanvasText;
    }}
    header, section {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 24px;
    }}
    header {{
      border-bottom: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
    }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ margin: 0; color: color-mix(in srgb, CanvasText 70%, transparent); }}
    a {{ color: inherit; }}
    .back {{ display: inline-block; margin-bottom: 10px; color: #3b82f6; text-decoration: none; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    .card {{
      display: grid;
      gap: 6px;
      padding: 14px;
      border: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
      border-radius: 8px;
      text-decoration: none;
      background: color-mix(in srgb, Canvas 92%, CanvasText 8%);
    }}
    .name {{ font-weight: 700; }}
    .meta, .desc, .empty {{ color: color-mix(in srgb, CanvasText 68%, transparent); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid color-mix(in srgb, CanvasText 12%, transparent);
      text-align: left;
      vertical-align: top;
    }}
    th {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      background: color-mix(in srgb, #3b82f6 20%, transparent);
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _tasks_table(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return '<p class="empty">No tasks yet.</p>'
    rows = "\n".join(
        f"""
        <tr>
          <td><span class="pill">{escape(task.get('status') or '')}</span></td>
          <td>{escape(task.get('title') or '')}<br><span class="meta">{escape(task.get('id') or '')}</span></td>
          <td>{escape(task.get('owner') or '')}</td>
          <td>{escape(task.get('target_agent') or '')}</td>
          <td>{escape(task.get('updated_at') or '')}</td>
        </tr>
        """
        for task in tasks
    )
    return f"""
    <table>
      <thead><tr><th>Status</th><th>Task</th><th>Owner</th><th>Target</th><th>Updated</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _events_table(events: list[dict[str, Any]]) -> str:
    if not events:
        return '<p class="empty">No events yet.</p>'
    rows = "\n".join(
        f"""
        <tr>
          <td>{escape(event.get('created_at') or '')}</td>
          <td>{escape(event.get('project') or '')}</td>
          <td>{escape(event.get('actor') or '')}</td>
          <td><span class="pill">{escape(event.get('type') or '')}</span></td>
          <td>{escape(event.get('body') or '')}</td>
        </tr>
        """
        for event in events
    )
    return f"""
    <table>
      <thead><tr><th>Time</th><th>Project</th><th>Actor</th><th>Type</th><th>Body</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    try:
        return int(value)
    except ValueError:
        return default


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    store = Store(settings.db_path, settings.artifact_dir)
    notifier = DiscordNotifier(settings.discord_webhook_url, settings.discord_webhook_routes)
    server = AgentBusHTTPServer(
        (settings.host, settings.port),
        store,
        notifier,
        settings.token,
        settings.read_token,
        settings.public_read,
    )
    print(f"agent-bus listening on http://{settings.host}:{settings.port}", file=sys.stderr)
    print(f"db: {settings.db_path}", file=sys.stderr)
    if settings.host != "127.0.0.1" and not settings.token:
        print("warning: AGENT_BUS_TOKEN is empty while binding to a non-local host", file=sys.stderr)
    if settings.read_token:
        print("read token: enabled", file=sys.stderr)
    if settings.public_read:
        print("public read: enabled", file=sys.stderr)
    if notifier.enabled():
        print("discord webhook: enabled", file=sys.stderr)
    else:
        print("discord webhook: disabled", file=sys.stderr)
    server.serve_forever()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
