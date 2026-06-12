#!/usr/bin/env bash
set -euo pipefail

if [ -z "${AGENT_BUS_URL:-}" ]; then
  cat >&2 <<'EOF'
AGENT_BUS_URL is required.

Example:
  curl -fsSL https://raw.githubusercontent.com/takatronix/agent-bus/main/scripts/team-connect.sh \
    | AGENT_BUS_URL=https://agent-bus.example.com \
      AGENT_BUS_TOKEN=... \
      AGENT_BUS_DEFAULT_PROJECT=agent-bus \
      bash
EOF
  exit 2
fi

INSTALL_DIR="${AGENT_BUS_INSTALL_DIR:-$HOME/.agent-bus}"
REPO_URL="${AGENT_BUS_REPO_URL:-https://github.com/takatronix/agent-bus.git}"
AGENT_BUS_NAME="${AGENT_BUS_NAME:-agent-bus}"
AGENT_BUS_TOKEN="${AGENT_BUS_TOKEN:-}"
AGENT_BUS_DEFAULT_PROJECT="${AGENT_BUS_DEFAULT_PROJECT:-}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 2
  fi
}

install_repo() {
  need_cmd git
  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
  else
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  chmod +x "$INSTALL_DIR/bin/agent-bus" "$INSTALL_DIR/bin/agentctl" "$INSTALL_DIR/bin/agent-bus-mcp"
}

write_env() {
  umask 077
  cat > "$INSTALL_DIR/.env" <<EOF
AGENT_BUS_URL=$AGENT_BUS_URL
AGENT_BUS_TOKEN=$AGENT_BUS_TOKEN
AGENT_BUS_DEFAULT_PROJECT=$AGENT_BUS_DEFAULT_PROJECT
EOF
}

http_smoke() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$AGENT_BUS_URL/healthz" >/dev/null || {
      echo "warning: could not reach $AGENT_BUS_URL/healthz" >&2
      return
    }
  fi
  "$INSTALL_DIR/bin/agentctl" agent heartbeat \
    --name "${USER:-team-member}-$(hostname | cut -d. -f1)" \
    --capability team \
    --capability mcp >/dev/null || {
      echo "warning: heartbeat failed; check AGENT_BUS_TOKEN if auth is enabled" >&2
    }
}

configure_cursor() {
  local config="$HOME/.cursor/mcp.json"
  mkdir -p "$(dirname "$config")"
  AGENT_BUS_MCP_COMMAND="$INSTALL_DIR/bin/agent-bus-mcp" \
  AGENT_BUS_MCP_CONFIG="$config" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["AGENT_BUS_MCP_CONFIG"])
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        data = {}
else:
    data = {}

env = {"AGENT_BUS_URL": os.environ["AGENT_BUS_URL"]}
if os.environ.get("AGENT_BUS_TOKEN"):
    env["AGENT_BUS_TOKEN"] = os.environ["AGENT_BUS_TOKEN"]
if os.environ.get("AGENT_BUS_DEFAULT_PROJECT"):
    env["AGENT_BUS_DEFAULT_PROJECT"] = os.environ["AGENT_BUS_DEFAULT_PROJECT"]

data.setdefault("mcpServers", {})[os.environ.get("AGENT_BUS_NAME", "agent-bus")] = {
    "type": "stdio",
    "command": os.environ["AGENT_BUS_MCP_COMMAND"],
    "env": env,
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  echo "configured Cursor MCP: $config"
}

configure_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude not found; skipped Claude Code MCP config"
    return
  fi
  claude mcp remove "$AGENT_BUS_NAME" -s user >/dev/null 2>&1 || true
  local args=(mcp add -s user "$AGENT_BUS_NAME" -e "AGENT_BUS_URL=$AGENT_BUS_URL")
  if [ -n "$AGENT_BUS_TOKEN" ]; then
    args+=(-e "AGENT_BUS_TOKEN=$AGENT_BUS_TOKEN")
  fi
  if [ -n "$AGENT_BUS_DEFAULT_PROJECT" ]; then
    args+=(-e "AGENT_BUS_DEFAULT_PROJECT=$AGENT_BUS_DEFAULT_PROJECT")
  fi
  claude "${args[@]}" -- "$INSTALL_DIR/bin/agent-bus-mcp" >/dev/null
  echo "configured Claude Code MCP"
}

configure_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex not found; skipped Codex MCP config"
    return
  fi
  codex mcp remove "$AGENT_BUS_NAME" >/dev/null 2>&1 || true
  local args=(mcp add "$AGENT_BUS_NAME" --env "AGENT_BUS_URL=$AGENT_BUS_URL")
  if [ -n "$AGENT_BUS_TOKEN" ]; then
    args+=(--env "AGENT_BUS_TOKEN=$AGENT_BUS_TOKEN")
  fi
  if [ -n "$AGENT_BUS_DEFAULT_PROJECT" ]; then
    args+=(--env "AGENT_BUS_DEFAULT_PROJECT=$AGENT_BUS_DEFAULT_PROJECT")
  fi
  codex "${args[@]}" -- "$INSTALL_DIR/bin/agent-bus-mcp" >/dev/null
  echo "configured Codex MCP"
}

need_cmd python3
install_repo
write_env
http_smoke
configure_cursor
configure_claude
configure_codex

cat <<EOF

Agent Bus team connection complete.

URL: $AGENT_BUS_URL
Install dir: $INSTALL_DIR
Default project: ${AGENT_BUS_DEFAULT_PROJECT:-none}

Reload Cursor/Claude/Codex if they were already open.
EOF
