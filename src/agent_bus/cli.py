from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import click

from .client import AgentBusClient
from .config import load_dotenv
from .runner import default_agent_name, run_codex_task, table


def client() -> AgentBusClient:
    load_dotenv()
    return AgentBusClient()


def emit(data: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        click.echo(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2))


@click.group()
def main() -> None:
    """Agent Bus command-line client."""


@main.group()
def task() -> None:
    """Create, list, claim, and update tasks."""


@task.command("create")
@click.argument("title")
@click.option("--body", default="", help="Task body.")
@click.option("--body-file", type=click.Path(exists=True, dir_okay=False), help="Read body from file.")
@click.option("--created-by", default="human")
@click.option("--priority", default="normal")
@click.option("--project")
@click.option("--repo")
@click.option("--branch")
@click.option("--target-agent")
@click.option("--ref", "refs", multiple=True)
@click.option("--json", "as_json", is_flag=True)
def task_create(
    title: str,
    body: str,
    body_file: str | None,
    created_by: str,
    priority: str,
    project: str | None,
    repo: str | None,
    branch: str | None,
    target_agent: str | None,
    refs: tuple[str, ...],
    as_json: bool,
) -> None:
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    data = client().post(
        "/tasks",
        {
            "title": title,
            "body": body,
            "created_by": created_by,
            "priority": priority,
            "project": project,
            "repo": repo,
            "branch": branch,
            "target_agent": target_agent,
            "refs": list(refs),
        },
    )["task"]
    emit(data if as_json else f"{data['id']} {data['status']} {data['title']}", as_json)


@task.command("list")
@click.option("--status")
@click.option("--project")
@click.option("--owner")
@click.option("--target-agent")
@click.option("--limit", default=20)
@click.option("--json", "as_json", is_flag=True)
def task_list(
    status: str | None,
    project: str | None,
    owner: str | None,
    target_agent: str | None,
    limit: int,
    as_json: bool,
) -> None:
    params = []
    for key, value in [
        ("status", status),
        ("project", project),
        ("owner", owner),
        ("target_agent", target_agent),
        ("limit", limit),
    ]:
        if value:
            params.append(f"{key}={value}")
    data = client().get("/tasks" + (f"?{'&'.join(params)}" if params else ""))["tasks"]
    emit(
        data if as_json else table(data, ["id", "project", "status", "priority", "owner", "target_agent", "title"]),
        as_json,
    )


@task.command("show")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True)
def task_show(task_id: str, as_json: bool) -> None:
    data = client().get(f"/tasks/{task_id}")["task"]
    emit(data, True if as_json else True)


@task.command("claim")
@click.argument("task_id")
@click.option("--agent", default=lambda: default_agent_name("agent"), show_default="agent-hostname")
@click.option("--json", "as_json", is_flag=True)
def task_claim(task_id: str, agent: str, as_json: bool) -> None:
    data = client().post(f"/tasks/{task_id}/claim", {"agent": agent})["task"]
    emit(data if as_json else f"{data['id']} claimed by {data['claimed_by']}", as_json)


@task.command("update")
@click.argument("task_id")
@click.option("--status")
@click.option("--project")
@click.option("--owner")
@click.option("--branch")
@click.option("--note", default="")
@click.option("--actor", default=lambda: default_agent_name("agent"), show_default="agent-hostname")
@click.option("--event-type")
@click.option("--json", "as_json", is_flag=True)
def task_update(
    task_id: str,
    status: str | None,
    project: str | None,
    owner: str | None,
    branch: str | None,
    note: str,
    actor: str,
    event_type: str | None,
    as_json: bool,
) -> None:
    payload: dict[str, Any] = {"actor": actor, "note": note}
    if status:
        payload["status"] = status
    if project:
        payload["project"] = project
    if owner:
        payload["owner"] = owner
    if branch:
        payload["branch"] = branch
    if event_type:
        payload["event_type"] = event_type
    data = client().post(f"/tasks/{task_id}/update", payload)["task"]
    emit(data if as_json else f"{data['id']} {data['status']}", as_json)


@main.group()
def event() -> None:
    """Post and list events."""


@event.command("post")
@click.option("--task-id")
@click.option("--type", "event_type", default="message")
@click.option("--actor", default=lambda: default_agent_name("agent"), show_default="agent-hostname")
@click.option("--target")
@click.option("--body", default="")
@click.option("--body-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--severity", default="info")
@click.option("--ref", "refs", multiple=True)
@click.option("--json", "as_json", is_flag=True)
def event_post(
    task_id: str | None,
    event_type: str,
    actor: str,
    target: str | None,
    body: str,
    body_file: str | None,
    severity: str,
    refs: tuple[str, ...],
    as_json: bool,
) -> None:
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    data = client().post(
        "/events",
        {
            "task_id": task_id,
            "type": event_type,
            "actor": actor,
            "target": target,
            "body": body,
            "severity": severity,
            "refs": list(refs),
        },
    )["event"]
    emit(data if as_json else f"{data['id']} {data['type']} {data['actor']}", as_json)


@event.command("list")
@click.option("--task-id")
@click.option("--limit", default=20)
@click.option("--json", "as_json", is_flag=True)
def event_list(task_id: str | None, limit: int, as_json: bool) -> None:
    params = [f"limit={limit}"]
    if task_id:
        params.append(f"task_id={task_id}")
    data = client().get(f"/events?{'&'.join(params)}")["events"]
    emit(data if as_json else table(data, ["id", "task_id", "type", "actor", "severity", "created_at"]), as_json)


@main.group()
def artifact() -> None:
    """Attach and list artifacts."""


@artifact.command("add")
@click.option("--task-id")
@click.option("--actor", default=lambda: default_agent_name("agent"), show_default="agent-hostname")
@click.option("--kind", default="text")
@click.option("--path")
@click.option("--url")
@click.option("--content-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--summary", default="")
@click.option("--json", "as_json", is_flag=True)
def artifact_add(
    task_id: str | None,
    actor: str,
    kind: str,
    path: str | None,
    url: str | None,
    content_file: str | None,
    summary: str,
    as_json: bool,
) -> None:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "actor": actor,
        "kind": kind,
        "path": path,
        "url": url,
        "summary": summary,
    }
    if content_file:
        payload["content"] = Path(content_file).read_text(encoding="utf-8")
    data = client().post("/artifacts", payload)["artifact"]
    emit(data if as_json else f"{data['id']} {data.get('path') or data.get('url') or ''}", as_json)


@artifact.command("list")
@click.option("--task-id")
@click.option("--limit", default=20)
@click.option("--json", "as_json", is_flag=True)
def artifact_list(task_id: str | None, limit: int, as_json: bool) -> None:
    params = [f"limit={limit}"]
    if task_id:
        params.append(f"task_id={task_id}")
    data = client().get(f"/artifacts?{'&'.join(params)}")["artifacts"]
    emit(data if as_json else table(data, ["id", "task_id", "kind", "path", "url", "summary"]), as_json)


@main.group()
def agent() -> None:
    """Register and list agents."""


@agent.command("heartbeat")
@click.option("--name", default=lambda: default_agent_name("agent"), show_default="agent-hostname")
@click.option("--capability", "capabilities", multiple=True)
@click.option("--status", default="online")
@click.option("--json", "as_json", is_flag=True)
def agent_heartbeat(name: str, capabilities: tuple[str, ...], status: str, as_json: bool) -> None:
    data = client().post(
        "/agents/heartbeat",
        {"name": name, "status": status, "capabilities": list(capabilities)},
    )["agent"]
    emit(data if as_json else f"{data['name']} {data['status']} {data['last_seen_at']}", as_json)


@agent.command("list")
@click.option("--json", "as_json", is_flag=True)
def agent_list(as_json: bool) -> None:
    data = client().get("/agents")["agents"]
    emit(data if as_json else table(data, ["name", "status", "last_seen_at"]), as_json)


@main.group()
def codex() -> None:
    """Run Codex against Agent Bus tasks."""


@codex.command("run")
@click.argument("task_id")
@click.option("--agent", default=lambda: default_agent_name("codex"), show_default="codex-hostname")
@click.option("--workdir", type=click.Path(file_okay=False), default=os.getcwd)
@click.option("--sandbox", default="workspace-write")
@click.option("--extra-prompt")
@click.option("--codex-bin", default="codex")
def codex_run(
    task_id: str,
    agent: str,
    workdir: str,
    sandbox: str,
    extra_prompt: str | None,
    codex_bin: str,
) -> None:
    try:
        raise SystemExit(
            run_codex_task(
                client(),
                task_id=task_id,
                agent=agent,
                workdir=workdir,
                sandbox=sandbox,
                extra_prompt=extra_prompt,
                codex_bin=codex_bin,
            )
        )
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
