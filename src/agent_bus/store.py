from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .util import dumps, loads, new_id, now_iso, slugify


TASK_STATUSES = {
    "open",
    "claimed",
    "running",
    "blocked",
    "review_requested",
    "done",
    "failed",
    "canceled",
}


class Store:
    def __init__(self, db_path: str | Path, artifact_dir: str | Path | None = None):
        self.db_path = Path(db_path)
        self.artifact_dir = Path(artifact_dir) if artifact_dir else self.db_path.parent / "artifacts"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    project TEXT,
                    repo TEXT,
                    branch TEXT,
                    created_by TEXT,
                    owner TEXT,
                    target_agent TEXT,
                    claimed_by TEXT,
                    claimed_at TEXT,
                    refs_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target TEXT,
                    body TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'info',
                    refs_json TEXT NOT NULL DEFAULT '[]',
                    data_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'text',
                    path TEXT,
                    url TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    name TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'online',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_seen_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner);
                CREATE INDEX IF NOT EXISTS idx_events_task_id_created_at ON events(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON artifacts(task_id);
                """
            )
            self._migrate_db(conn)

    def _migrate_db(self, conn: sqlite3.Connection) -> None:
        task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "project" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN project TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project)")

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        task_id = payload.get("id") or new_id("task")
        status = payload.get("status", "open")
        if status not in TASK_STATUSES:
            raise ValueError(f"invalid task status: {status}")

        row = {
            "id": task_id,
            "title": payload["title"],
            "body": payload.get("body", ""),
            "status": status,
            "priority": payload.get("priority", "normal"),
            "project": payload.get("project"),
            "repo": payload.get("repo"),
            "branch": payload.get("branch"),
            "created_by": payload.get("created_by") or payload.get("actor") or "human",
            "owner": payload.get("owner"),
            "target_agent": payload.get("target_agent"),
            "claimed_by": None,
            "claimed_at": None,
            "refs_json": dumps(payload.get("refs", [])),
            "metadata_json": dumps(payload.get("metadata", {})),
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, title, body, status, priority, project, repo, branch, created_by, owner,
                    target_agent, claimed_by, claimed_at, refs_json, metadata_json,
                    created_at, updated_at
                ) VALUES (
                    :id, :title, :body, :status, :priority, :project, :repo, :branch, :created_by,
                    :owner, :target_agent, :claimed_by, :claimed_at, :refs_json,
                    :metadata_json, :created_at, :updated_at
                )
                """,
                row,
            )
        return self.get_task(task_id)

    def list_tasks(
        self,
        status: str | None = None,
        project: str | None = None,
        owner: str | None = None,
        target_agent: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if project:
            clauses.append("project = :project")
            params["project"] = project
        if owner:
            clauses.append("owner = :owner")
            params["owner"] = owner
        if target_agent:
            clauses.append("(target_agent = :target_agent OR target_agent IS NULL)")
            params["target_agent"] = target_agent
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT :limit", params
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def claim_task(self, task_id: str, agent: str) -> dict[str, Any]:
        now = now_iso()
        with self.connect() as conn:
            row = conn.execute("SELECT status, claimed_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["claimed_by"] and row["claimed_by"] != agent and row["status"] not in {"open", "blocked"}:
                raise RuntimeError(f"task already claimed by {row['claimed_by']}")
            conn.execute(
                """
                UPDATE tasks
                SET status = 'claimed', owner = ?, claimed_by = ?, claimed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (agent, agent, now, now, task_id),
            )
        return self.get_task(task_id)

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "body",
            "status",
            "priority",
            "project",
            "repo",
            "branch",
            "owner",
            "target_agent",
        }
        if "status" in payload and payload["status"] not in TASK_STATUSES:
            raise ValueError(f"invalid task status: {payload['status']}")
        updates = {k: payload[k] for k in allowed if k in payload}
        now = now_iso()
        if "refs" in payload:
            updates["refs_json"] = dumps(payload["refs"])
        if "metadata" in payload:
            updates["metadata_json"] = dumps(payload["metadata"])
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = now
        parts = ", ".join(f"{key} = :{key}" for key in updates)
        updates["id"] = task_id
        with self.connect() as conn:
            cur = conn.execute(f"UPDATE tasks SET {parts} WHERE id = :id", updates)
            if cur.rowcount == 0:
                raise KeyError(task_id)
        return self.get_task(task_id)

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        row = {
            "id": payload.get("id") or new_id("evt"),
            "task_id": payload.get("task_id"),
            "type": payload.get("type", "message"),
            "actor": payload.get("actor") or payload.get("from") or "unknown",
            "target": payload.get("target") or payload.get("to"),
            "body": payload.get("body", ""),
            "severity": payload.get("severity", "info"),
            "refs_json": dumps(payload.get("refs", [])),
            "data_json": dumps(payload.get("data", {})),
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id, task_id, type, actor, target, body, severity, refs_json, data_json, created_at
                ) VALUES (
                    :id, :task_id, :type, :actor, :target, :body, :severity, :refs_json, :data_json, :created_at
                )
                """,
                row,
            )
            if row["task_id"]:
                conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, row["task_id"]))
        return self.get_event(row["id"])

    def list_events(self, task_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(max(limit, 1), 500)}
        where = ""
        if task_id:
            where = "WHERE task_id = :task_id"
            params["task_id"] = task_id
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT :limit", params
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def get_event(self, event_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return self._event_from_row(row)

    def create_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        artifact_id = payload.get("id") or new_id("art")
        path = payload.get("path")
        content = payload.get("content")
        task_id = payload.get("task_id")
        kind = payload.get("kind", "text")
        if content is not None and path is None:
            task_dir = self.artifact_dir / slugify(task_id or "global")
            task_dir.mkdir(parents=True, exist_ok=True)
            suffix = ".md" if kind in {"markdown", "summary"} else ".txt"
            path = str(task_dir / f"{artifact_id}{suffix}")
            Path(path).write_text(str(content), encoding="utf-8")

        row = {
            "id": artifact_id,
            "task_id": task_id,
            "kind": kind,
            "path": path,
            "url": payload.get("url"),
            "summary": payload.get("summary", ""),
            "metadata_json": dumps(payload.get("metadata", {})),
            "created_at": now_iso(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (id, task_id, kind, path, url, summary, metadata_json, created_at)
                VALUES (:id, :task_id, :kind, :path, :url, :summary, :metadata_json, :created_at)
                """,
                row,
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return self._artifact_from_row(row)

    def list_artifacts(self, task_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}
        where = ""
        if task_id:
            where = "WHERE task_id = :task_id"
            params["task_id"] = task_id
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM artifacts {where} ORDER BY created_at DESC LIMIT :limit", params
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def heartbeat_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = payload["name"]
        now = now_iso()
        row = {
            "name": name,
            "status": payload.get("status", "online"),
            "capabilities_json": dumps(payload.get("capabilities", [])),
            "metadata_json": dumps(payload.get("metadata", {})),
            "last_seen_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (name, status, capabilities_json, metadata_json, last_seen_at)
                VALUES (:name, :status, :capabilities_json, :metadata_json, :last_seen_at)
                ON CONFLICT(name) DO UPDATE SET
                    status = excluded.status,
                    capabilities_json = excluded.capabilities_json,
                    metadata_json = excluded.metadata_json,
                    last_seen_at = excluded.last_seen_at
                """,
                row,
            )
        return self.get_agent(name)

    def get_agent(self, name: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        return self._agent_from_row(row)

    def list_agents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY last_seen_at DESC").fetchall()
        return [self._agent_from_row(row) for row in rows]

    def _task_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["refs"] = loads(item.pop("refs_json"), [])
        item["metadata"] = loads(item.pop("metadata_json"), {})
        return item

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["refs"] = loads(item.pop("refs_json"), [])
        item["data"] = loads(item.pop("data_json"), {})
        return item

    def _artifact_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = loads(item.pop("metadata_json"), {})
        return item

    def _agent_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["capabilities"] = loads(item.pop("capabilities_json"), [])
        item["metadata"] = loads(item.pop("metadata_json"), {})
        return item
