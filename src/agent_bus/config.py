from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    artifact_dir: Path
    host: str
    port: int
    discord_webhook_url: str | None
    token: str | None


def load_settings() -> Settings:
    load_dotenv()
    root = Path(__file__).resolve().parents[2]
    db_path = Path(os.environ.get("AGENT_BUS_DB", root / "data" / "agent-bus.sqlite3"))
    artifact_dir = Path(os.environ.get("AGENT_BUS_ARTIFACT_DIR", root / "artifacts"))
    return Settings(
        db_path=db_path,
        artifact_dir=artifact_dir,
        host=os.environ.get("AGENT_BUS_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENT_BUS_PORT", "8765")),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL") or None,
        token=os.environ.get("AGENT_BUS_TOKEN") or None,
    )
