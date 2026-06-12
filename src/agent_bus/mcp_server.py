from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from .client import AgentBusClient
from .config import load_dotenv


def _client() -> AgentBusClient:
    load_dotenv()
    return AgentBusClient()


def _default_project() -> str | None:
    return os.environ.get("AGENT_BUS_DEFAULT_PROJECT") or None


INSTRUCTIONS = (
    "Use Agent Bus as the shared coordination layer for AI agents. "
    "Claim tasks before working, post concise progress events, attach large logs as artifacts, "
    "and mark tasks blocked when human input is required."
)


def _tool_create_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(
        "/tasks",
        {
            "title": arguments["title"],
            "body": arguments.get("body", ""),
            "created_by": arguments.get("created_by", "mcp"),
            "priority": arguments.get("priority", "normal"),
            "project": arguments.get("project") or _default_project(),
            "repo": arguments.get("repo"),
            "branch": arguments.get("branch"),
            "target_agent": arguments.get("target_agent"),
            "refs": arguments.get("refs") or [],
        },
    )


def _tool_create_project(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(
        "/projects",
        {
            "name": arguments["name"],
            "title": arguments.get("title") or arguments["name"],
            "description": arguments.get("description", ""),
            "status": arguments.get("status", "active"),
            "metadata": arguments.get("metadata") or {},
        },
    )


def _tool_list_projects(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().get(f"/projects?limit={arguments.get('limit', 50)}")


def _tool_get_project_history(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().get(f"/projects/{arguments['name']}/history?limit={arguments.get('limit', 50)}")


def _tool_list_tasks(arguments: dict[str, Any]) -> dict[str, Any]:
    params = [f"limit={arguments.get('limit', 20)}"]
    if not arguments.get("project") and _default_project():
        arguments = {**arguments, "project": _default_project()}
    for key in ("status", "project", "owner", "target_agent"):
        if arguments.get(key):
            params.append(f"{key}={arguments[key]}")
    return _client().get(f"/tasks?{'&'.join(params)}")


def _tool_get_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().get(f"/tasks/{arguments['task_id']}")


def _tool_claim_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(f"/tasks/{arguments['task_id']}/claim", {"agent": arguments["agent"]})


def _tool_update_task(arguments: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"actor": arguments.get("actor", "mcp"), "note": arguments.get("note", "")}
    for key in ("status", "event_type", "project", "branch", "owner"):
        if arguments.get(key):
            payload[key] = arguments[key]
    return _client().post(f"/tasks/{arguments['task_id']}/update", payload)


def _tool_post_event(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(
        "/events",
        {
            "task_id": arguments.get("task_id"),
            "project": arguments.get("project") or _default_project(),
            "type": arguments.get("event_type", "message"),
            "actor": arguments["actor"],
            "target": arguments.get("target"),
            "body": arguments["body"],
            "severity": arguments.get("severity", "info"),
            "refs": arguments.get("refs") or [],
        },
    )


def _tool_list_events(arguments: dict[str, Any]) -> dict[str, Any]:
    params = [f"limit={arguments.get('limit', 20)}"]
    if arguments.get("task_id"):
        params.append(f"task_id={arguments['task_id']}")
    if arguments.get("project") or _default_project():
        params.append(f"project={arguments.get('project') or _default_project()}")
    return _client().get(f"/events?{'&'.join(params)}")


def _tool_attach_artifact(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(
        "/artifacts",
        {
            "task_id": arguments.get("task_id"),
            "actor": arguments.get("actor", "mcp"),
            "kind": arguments.get("kind", "text"),
            "summary": arguments.get("summary", ""),
            "path": arguments.get("path"),
            "url": arguments.get("url"),
            "content": arguments.get("content"),
        },
    )


def _tool_heartbeat_agent(arguments: dict[str, Any]) -> dict[str, Any]:
    return _client().post(
        "/agents/heartbeat",
        {
            "name": arguments["name"],
            "status": arguments.get("status", "online"),
            "capabilities": arguments.get("capabilities") or [],
        },
    )


TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "create_project": _tool_create_project,
    "list_projects": _tool_list_projects,
    "get_project_history": _tool_get_project_history,
    "create_task": _tool_create_task,
    "list_tasks": _tool_list_tasks,
    "get_task": _tool_get_task,
    "claim_task": _tool_claim_task,
    "update_task": _tool_update_task,
    "post_event": _tool_post_event,
    "list_events": _tool_list_events,
    "attach_artifact": _tool_attach_artifact,
    "heartbeat_agent": _tool_heartbeat_agent,
}


TOOLS = [
    {
        "name": "create_project",
        "description": "Create or update a project namespace for tasks and history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_projects",
        "description": "List project namespaces with task counts.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_project_history",
        "description": "Read a project's tasks and event history.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["name"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a task for an agent to claim and work on.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "created_by": {"type": "string"},
                "priority": {"type": "string"},
                "project": {"type": "string"},
                "repo": {"type": "string"},
                "branch": {"type": "string"},
                "target_agent": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks, optionally filtering by status, owner, or target agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "project": {"type": "string"},
                "owner": {"type": "string"},
                "target_agent": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_task",
        "description": "Read one task by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "claim_task",
        "description": "Claim a task before starting work.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}, "agent": {"type": "string"}},
            "required": ["task_id", "agent"],
        },
    },
    {
        "name": "update_task",
        "description": "Update task status and optionally emit a status event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "actor": {"type": "string"},
                "status": {"type": "string"},
                "note": {"type": "string"},
                "event_type": {"type": "string"},
                "project": {"type": "string"},
                "branch": {"type": "string"},
                "owner": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "post_event",
        "description": "Post a concise event or message to the shared bus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor": {"type": "string"},
                "body": {"type": "string"},
                "task_id": {"type": "string"},
                "project": {"type": "string"},
                "event_type": {"type": "string"},
                "target": {"type": "string"},
                "severity": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["actor", "body"],
        },
    },
    {
        "name": "list_events",
        "description": "List recent events, optionally for one task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "project": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "attach_artifact",
        "description": "Attach a file path, URL, or text content artifact to a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "actor": {"type": "string"},
                "kind": {"type": "string"},
                "summary": {"type": "string"},
                "path": {"type": "string"},
                "url": {"type": "string"},
                "content": {"type": "string"},
            },
        },
    },
    {
        "name": "heartbeat_agent",
        "description": "Register or refresh an agent heartbeat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "status": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
    },
]


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised by invoking without optional dep.
    FastMCP = None  # type: ignore[assignment]


if FastMCP is not None:
    mcp = FastMCP(
        "agent-bus",
        instructions=INSTRUCTIONS,
    )

    @mcp.tool()
    def create_project(
        name: str,
        title: str | None = None,
        description: str = "",
        status: str = "active",
    ) -> dict[str, Any]:
        """Create or update a project namespace for tasks and history."""
        return _client().post(
            "/projects",
            {"name": name, "title": title or name, "description": description, "status": status},
        )

    @mcp.tool()
    def list_projects(limit: int = 50) -> dict[str, Any]:
        """List project namespaces with task counts."""
        return _client().get(f"/projects?limit={limit}")

    @mcp.tool()
    def get_project_history(name: str, limit: int = 50) -> dict[str, Any]:
        """Read a project's tasks and event history."""
        return _client().get(f"/projects/{name}/history?limit={limit}")

    @mcp.tool()
    def create_task(
        title: str,
        body: str = "",
        created_by: str = "mcp",
        priority: str = "normal",
        repo: str | None = None,
        project: str | None = None,
        branch: str | None = None,
        target_agent: str | None = None,
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a task for an agent to claim and work on."""
        return _client().post(
            "/tasks",
            {
                "title": title,
                "body": body,
                "created_by": created_by,
                "priority": priority,
                "project": project or _default_project(),
                "repo": repo,
                "branch": branch,
                "target_agent": target_agent,
                "refs": refs or [],
            },
        )

    @mcp.tool()
    def list_tasks(
        status: str | None = None,
        project: str | None = None,
        owner: str | None = None,
        target_agent: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List tasks, optionally filtering by status, owner, or target agent."""
        params = [f"limit={limit}"]
        project = project or _default_project()
        if status:
            params.append(f"status={status}")
        if project:
            params.append(f"project={project}")
        if owner:
            params.append(f"owner={owner}")
        if target_agent:
            params.append(f"target_agent={target_agent}")
        return _client().get(f"/tasks?{'&'.join(params)}")

    @mcp.tool()
    def get_task(task_id: str) -> dict[str, Any]:
        """Read one task by id."""
        return _client().get(f"/tasks/{task_id}")

    @mcp.tool()
    def claim_task(task_id: str, agent: str) -> dict[str, Any]:
        """Claim a task before starting work."""
        return _client().post(f"/tasks/{task_id}/claim", {"agent": agent})

    @mcp.tool()
    def update_task(
        task_id: str,
        actor: str = "mcp",
        status: str | None = None,
        note: str = "",
        event_type: str | None = None,
        project: str | None = None,
        branch: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Update task status and optionally emit a status event."""
        payload: dict[str, Any] = {"actor": actor, "note": note}
        if status:
            payload["status"] = status
        if event_type:
            payload["event_type"] = event_type
        if project:
            payload["project"] = project
        if branch:
            payload["branch"] = branch
        if owner:
            payload["owner"] = owner
        return _client().post(f"/tasks/{task_id}/update", payload)

    @mcp.tool()
    def post_event(
        actor: str,
        body: str,
        task_id: str | None = None,
        project: str | None = None,
        event_type: str = "message",
        target: str | None = None,
        severity: str = "info",
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Post a concise event or message to the shared bus."""
        return _client().post(
            "/events",
            {
                "task_id": task_id,
                "project": project or _default_project(),
                "type": event_type,
                "actor": actor,
                "target": target,
                "body": body,
                "severity": severity,
                "refs": refs or [],
            },
        )

    @mcp.tool()
    def list_events(
        task_id: str | None = None,
        project: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent events, optionally for one task."""
        params = [f"limit={limit}"]
        if task_id:
            params.append(f"task_id={task_id}")
        project = project or _default_project()
        if project:
            params.append(f"project={project}")
        return _client().get(f"/events?{'&'.join(params)}")

    @mcp.tool()
    def attach_artifact(
        task_id: str | None = None,
        actor: str = "mcp",
        kind: str = "text",
        summary: str = "",
        path: str | None = None,
        url: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Attach a file path, URL, or text content artifact to a task."""
        return _client().post(
            "/artifacts",
            {
                "task_id": task_id,
                "actor": actor,
                "kind": kind,
                "summary": summary,
                "path": path,
                "url": url,
                "content": content,
            },
        )

    @mcp.tool()
    def heartbeat_agent(
        name: str,
        status: str = "online",
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register or refresh an agent heartbeat."""
        return _client().post(
            "/agents/heartbeat",
            {"name": name, "status": status, "capabilities": capabilities or []},
        )


def main() -> None:
    if FastMCP is None:
        _run_minimal_stdio_server()
        return
    mcp.run()


def _run_minimal_stdio_server() -> None:
    print("agent-bus-mcp running with built-in minimal stdio transport", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = _handle_jsonrpc(message)
        except Exception as exc:
            response = _jsonrpc_error(None, -32700, f"parse error: {exc}")
        if response is not None:
            print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)


def _handle_jsonrpc(message: dict[str, Any]) -> dict[str, Any] | None:
    if "id" not in message:
        return None
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agent-bus", "version": "0.1.0"},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name not in TOOL_HANDLERS:
                raise KeyError(f"unknown tool: {name}")
            tool_result = TOOL_HANDLERS[name](arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(tool_result, ensure_ascii=False, indent=2)}],
                "structuredContent": tool_result,
            }
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return _jsonrpc_error(request_id, -32601, f"method not found: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return _jsonrpc_error(request_id, -32000, str(exc))


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
