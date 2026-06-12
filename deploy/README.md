# Deploy Agent Bus

For team use, expose one Agent Bus over HTTPS and give members only:

```text
AGENT_BUS_URL=https://your-agent-bus.example.com
AGENT_BUS_TOKEN=<shared-write-token>
AGENT_BUS_DEFAULT_PROJECT=<project-name>
```

HTTPS should be handled by the hosting layer, not by the Python process.

## Fastest Options

### Option A: Managed Web Service

Use Render, Railway, Fly.io, or a small VPS. The app listens on HTTP inside the platform, and the platform provides HTTPS.

Required environment:

```text
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_TOKEN=<long random token>
AGENT_BUS_DB=/data/agent-bus.sqlite3
AGENT_BUS_ARTIFACT_DIR=/data/artifacts
DISCORD_WEBHOOK_URL=<fallback webhook, optional>
```

You need persistent storage mounted at `/data` if you use SQLite.

Generate a token:

```bash
openssl rand -hex 32
```

### Option B: Current Machine + Cloudflare Tunnel

Run Agent Bus locally, then expose it through Cloudflare Tunnel. Team members connect to the public HTTPS URL. This avoids opening inbound firewall ports.

Server:

```bash
export AGENT_BUS_HOST=127.0.0.1
export AGENT_BUS_PORT=8765
export AGENT_BUS_TOKEN="$(openssl rand -hex 32)"
/home/aspa/agent-bus/bin/agent-bus
```

Tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

Use the generated `https://...trycloudflare.com` URL as `AGENT_BUS_URL`.

## Team Member Setup

Each member runs:

```bash
curl -fsSL https://raw.githubusercontent.com/takatronix/agent-bus/main/scripts/team-connect.sh \
  | AGENT_BUS_URL=https://your-agent-bus.example.com \
    AGENT_BUS_TOKEN=<shared-write-token> \
    AGENT_BUS_DEFAULT_PROJECT=agent-bus \
    bash
```

The script configures:

```text
Claude Code user MCP
Cursor global MCP
Codex MCP, if installed
```

Then reload the AI client.
