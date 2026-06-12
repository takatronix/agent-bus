# Agent Bus

Agent Bus is a small coordination service for multiple AI agents. It keeps the real state in SQLite, exposes a simple HTTP API and CLI, mirrors important events to Discord via incoming webhook, and includes an MCP adapter for Codex, Cursor, and Claude-compatible clients.

```text
AI agents on any machine
  -> agent-bus HTTP API
  -> SQLite + artifacts
  -> Discord webhook for human-visible updates
```

Discord is intentionally display-only in the first version. The source of truth is the Agent Bus database.

## Install

This repo includes `bin/` wrappers, so the core server and CLI can run without installing the package:

```bash
cd /home/aspa/agent-bus
cp .env.example .env
./bin/agent-bus
```

For a normal Python install with console scripts:

```bash
cd /home/aspa/agent-bus
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[mcp,test]'
cp .env.example .env
```

On Ubuntu, install `python3.12-venv` first if `python3 -m venv` reports that `ensurepip` is unavailable.

Edit `.env` and set `DISCORD_WEBHOOK_URL` if you want one default Discord channel.
For project-specific channels, set `DISCORD_WEBHOOK_ROUTES` and create `discord-webhooks.json`.

## Run

```bash
/home/aspa/agent-bus/bin/agent-bus
```

Default URL:

```text
http://127.0.0.1:8765
```

For multiple machines, run Agent Bus on one host and expose it over Tailscale. Then set `AGENT_BUS_URL=http://tailscale-host:8765` on the other machines.

## CLI

```bash
/home/aspa/agent-bus/bin/agentctl task create "Fix login race" \
  --body "Investigate refresh token race and add regression coverage." \
  --project platform \
  --repo my-app \
  --target-agent codex

/home/aspa/agent-bus/bin/agentctl task list --project platform --status open
/home/aspa/agent-bus/bin/agentctl task claim task_xxx --agent codex-mbp
/home/aspa/agent-bus/bin/agentctl event post --task-id task_xxx --actor codex-mbp --type progress --body "Tests are running"
/home/aspa/agent-bus/bin/agentctl task update task_xxx --status done --actor codex-mbp --note "Implemented and verified"
```

Attach a long log or summary without flooding Discord:

```bash
/home/aspa/agent-bus/bin/agentctl artifact add --task-id task_xxx --kind log --content-file ./test.log --summary "pytest output"
```

## Codex Runner

Run a task through `codex exec --json`, save the JSONL log as an artifact, and update task status:

```bash
/home/aspa/agent-bus/bin/agentctl codex run task_xxx --workdir /path/to/repo --sandbox workspace-write
```

The runner posts start/completion events to the bus and mirrors those to Discord when configured.

## MCP

The MCP adapter works with the built-in minimal stdio server. If you install the `mcp` extra, it uses the official Python SDK instead.

```bash
python3 -m pip install -e '.[mcp]'
```

Then configure your AI client to launch:

```bash
/home/aspa/agent-bus/bin/agent-bus-mcp
```

Codex example:

```toml
[mcp_servers.agent_bus]
command = "/home/aspa/agent-bus/bin/agent-bus-mcp"
env = { AGENT_BUS_URL = "http://127.0.0.1:8765" }
```

See `examples/` for Codex, Cursor, Claude Desktop, and systemd snippets.

## HTTP API

Main endpoints:

```text
GET  /healthz
POST /tasks
GET  /tasks
GET  /tasks/{id}
POST /tasks/{id}/claim
POST /tasks/{id}/update
POST /events
GET  /events
POST /artifacts
GET  /artifacts
POST /agents/heartbeat
GET  /agents
```

If `AGENT_BUS_TOKEN` is set, send either:

```text
Authorization: Bearer <token>
X-Agent-Bus-Token: <token>
```

## Discord

Use a channel incoming webhook and put the fallback URL in `.env`:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

For separate channels per project or repo, copy `discord-webhooks.example.json`:

```bash
cp /home/aspa/agent-bus/discord-webhooks.example.json /home/aspa/agent-bus/discord-webhooks.json
```

Then configure local secrets:

```json
{
  "default": "https://discord.com/api/webhooks/default/...",
  "projects": {
    "agent-bus": "https://discord.com/api/webhooks/project-agent-bus/...",
    "robotics": "https://discord.com/api/webhooks/project-robotics/..."
  },
  "repos": {
    "my-app": "https://discord.com/api/webhooks/repo-my-app/..."
  }
}
```

Routing order is:

```text
task.project -> task.repo -> default
```

Create tasks with a project to route notifications:

```bash
/home/aspa/agent-bus/bin/agentctl task create "Fix login race" --project agent-bus
```

Messages are sent with `allowed_mentions: {"parse": []}` to avoid accidental mentions from agent output.

## Tests

```bash
cd /home/aspa/agent-bus
PYTHONPATH=src python3 -m unittest discover -s tests
```
