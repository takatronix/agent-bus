from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .client import AgentBusClient


def default_agent_name(prefix: str = "codex") -> str:
    return f"{prefix}-{socket.gethostname().split('.')[0]}"


def build_task_prompt(task: dict[str, Any], extra: str | None = None) -> str:
    parts = [
        f"Agent Bus task: {task['id']}",
        f"Title: {task['title']}",
    ]
    if task.get("body"):
        parts.extend(["", "Body:", task["body"]])
    if task.get("repo"):
        parts.append(f"\nRepo: {task['repo']}")
    if task.get("branch"):
        parts.append(f"Branch: {task['branch']}")
    if task.get("refs"):
        parts.extend(["", "Refs:", "\n".join(f"- {ref}" for ref in task["refs"])])
    if extra:
        parts.extend(["", "Additional instruction:", extra])
    parts.extend(
        [
            "",
            "Work pragmatically. Post concise progress to Agent Bus via agentctl if useful.",
            "At the end, summarize files changed, verification run, and any remaining risk.",
        ]
    )
    return "\n".join(parts)


def run_codex_task(
    client: AgentBusClient,
    task_id: str,
    agent: str | None = None,
    workdir: str | None = None,
    sandbox: str = "workspace-write",
    extra_prompt: str | None = None,
    codex_bin: str = "codex",
) -> int:
    agent_name = agent or default_agent_name("codex")
    task = client.get(f"/tasks/{task_id}")["task"]
    client.post("/agents/heartbeat", {"name": agent_name, "capabilities": ["code", "test", "review"]})
    client.post(f"/tasks/{task_id}/claim", {"agent": agent_name})
    client.post(
        "/events",
        {
            "task_id": task_id,
            "type": "progress",
            "actor": agent_name,
            "body": f"starting codex exec in {workdir or Path.cwd()}",
        },
    )

    prompt = build_task_prompt(task, extra_prompt)
    cmd = [codex_bin, "exec", "--json", "--sandbox", sandbox, prompt]
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert proc.stdout is not None
    log_lines: list[str] = []
    final_messages: list[str] = []
    for line in proc.stdout:
        print(line, end="")
        log_lines.append(line)
        parsed = _try_json(line)
        if parsed and parsed.get("type") == "item.completed":
            item = parsed.get("item", {})
            if item.get("type") == "agent_message" and item.get("text"):
                final_messages.append(item["text"])
    code = proc.wait()
    summary = final_messages[-1] if final_messages else f"codex exited with code {code}"
    artifact = client.post(
        "/artifacts",
        {
            "task_id": task_id,
            "actor": agent_name,
            "kind": "jsonl",
            "summary": f"codex exec log, exit code {code}",
            "content": "".join(log_lines),
        },
    )["artifact"]
    status = "done" if code == 0 else "failed"
    client.post(
        f"/tasks/{task_id}/update",
        {
            "status": status,
            "actor": agent_name,
            "event_type": "completed" if code == 0 else "failed",
            "note": summary,
            "metadata": {"codex_exit_code": code, "log_artifact_id": artifact["id"]},
        },
    )
    return code


def _try_json(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def table(rows: Iterable[dict[str, Any]], columns: list[str]) -> str:
    rows = list(rows)
    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(str(row.get(column, ""))))
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    sep = "  ".join("-" * widths[column] for column in columns)
    lines = [header, sep]
    for row in rows:
        lines.append("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))
    return "\n".join(lines)
