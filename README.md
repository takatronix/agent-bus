# Agent Bus

Agent Bus は、複数の AI エージェントを同じプロジェクト上で協調させるための小さな中継サービスです。状態は SQLite に保存し、HTTP API / CLI / MCP adapter を提供します。重要なイベントは Discord webhook にも流せます。

```text
各マシンの AI エージェント
  -> Agent Bus HTTP API / MCP
  -> SQLite + artifacts
  -> Discord webhook
  -> Web UI でプロジェクト履歴を確認
```

Discord は人間向けの表示先です。正の状態は Agent Bus の DB に保存します。

## インストール

この repo には `bin/` wrapper が入っているので、pip install なしでもサーバと CLI を動かせます。

```bash
cd /home/aspa/agent-bus
cp .env.example .env
./bin/agent-bus
```

通常の Python package として入れる場合:

```bash
cd /home/aspa/agent-bus
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[mcp,test]'
cp .env.example .env
```

Ubuntu で `python3 -m venv` が `ensurepip` エラーになる場合は、先に `python3.12-venv` を入れてください。

## 起動

```bash
/home/aspa/agent-bus/bin/agent-bus
```

デフォルト URL:

```text
http://127.0.0.1:8765
```

チームで使う場合は、Agent Bus を 1つの HTTPS Webサービスとして公開し、メンバーには `AGENT_BUS_URL` と `AGENT_BUS_TOKEN` を配ります。公開方法は [deploy/README.md](deploy/README.md) を見てください。

## チームメンバーの接続

各メンバーはこれを実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/takatronix/agent-bus/main/scripts/team-connect.sh \
  | AGENT_BUS_URL=https://your-agent-bus.example.com \
    AGENT_BUS_TOKEN=<shared-write-token> \
    AGENT_BUS_DEFAULT_PROJECT=agent-bus \
    bash
```

この script は、インストール済みなら Claude Code / Cursor / Codex の MCP 設定を自動で追加します。すでに AI クライアントを開いている場合は reload してください。

## プロジェクトと履歴

Agent Bus は 1サーバ内に複数プロジェクトを作れます。

```text
1つの Agent Bus サーバ
  ├─ project: agent-bus
  │   ├─ tasks
  │   └─ event history
  ├─ project: robotics
  │   ├─ tasks
  │   └─ event history
  └─ project: ...
```

Web UI:

```text
GET /
GET /projects/<project-name>
GET /projects/<project-name>/history
```

プロジェクト作成と履歴確認:

```bash
/home/aspa/agent-bus/bin/agentctl project create agent-bus \
  --title "Agent Bus" \
  --description "AI エージェント間の共有作業場"

/home/aspa/agent-bus/bin/agentctl task create "Cursor をつなぐ" \
  --project agent-bus \
  --target-agent cursor

/home/aspa/agent-bus/bin/agentctl project history agent-bus
```

プロジェクトページでは以下を確認・設定できます。

```text
概要
Discord webhook
タスク一覧
イベント履歴
```

## 認証

公開運用では、アプリの token と Web UI の前段認証を分けるのが安全です。

```text
AGENT_BUS_TOKEN       AI/MCP/API の書き込み・管理用 token
AGENT_BUS_READ_TOKEN  ブラウザ/API の読み取り専用 token
AGENT_BUS_PUBLIC_READ 履歴を完全公開してよい場合だけ true
```

本番では Web UI を Cloudflare Access、Google/IAP、Caddy basic auth、または hosting provider の access control の後ろに置くことを推奨します。query string の token はローカル確認には便利ですが、長期運用の共有リンクには向きません。

読み取り専用でブラウザに出す場合:

```text
AGENT_BUS_READ_TOKEN=<read-token>
```

開く URL:

```text
https://your-agent-bus.example.com?read_token=<read-token>
https://your-agent-bus.example.com/projects/agent-bus?read_token=<read-token>
```

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

長いログや要約は Discord に直接流さず artifact として保存します。

```bash
/home/aspa/agent-bus/bin/agentctl artifact add --task-id task_xxx --kind log --content-file ./test.log --summary "pytest output"
```

## Codex Runner

`codex exec --json` で task を実行し、JSONL log を artifact に保存し、task status を更新できます。

```bash
/home/aspa/agent-bus/bin/agentctl codex run task_xxx --workdir /path/to/repo --sandbox workspace-write
```

## MCP

MCP adapter は内蔵の最小 stdio server だけで動きます。`mcp` extra を入れると公式 Python SDK 経由でも動きます。

```bash
python3 -m pip install -e '.[mcp]'
```

AI クライアントにはこの command を登録します。

```bash
/home/aspa/agent-bus/bin/agent-bus-mcp
```

Codex 設定例:

```toml
[mcp_servers.agent_bus]
command = "/home/aspa/agent-bus/bin/agent-bus-mcp"
env = { AGENT_BUS_URL = "http://127.0.0.1:8765" }
```

`examples/` に Codex、Cursor、Claude Desktop、systemd の設定例があります。

## HTTP API

主な endpoint:

```text
GET  /healthz
POST /projects
GET  /projects
GET  /projects/{name}
GET  /projects/{name}/history
POST /projects/{name}/settings
POST /projects/{name}/discord-webhook
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

`AGENT_BUS_TOKEN` を設定している場合は、どちらかを送ります。

```text
Authorization: Bearer <token>
X-Agent-Bus-Token: <token>
```

## Discord

fallback の Discord webhook は `.env` に入れます。

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

プロジェクトごとの Discord webhook は Web UI から設定できます。

```text
https://your-agent-bus.example.com/projects/agent-bus
```

保存された webhook URL は API に返さず、HTML にも再表示しません。UI では `Configured / Not configured` だけ表示します。保存・削除には書き込み用の `AGENT_BUS_TOKEN` が必要です。

file で一括管理したい場合は `discord-webhooks.example.json` をコピーします。

```bash
cp /home/aspa/agent-bus/discord-webhooks.example.json /home/aspa/agent-bus/discord-webhooks.json
```

形式:

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

通知先の優先順位:

```text
Web UI の project webhook
  -> discord-webhooks.json の project
  -> discord-webhooks.json の repo
  -> DISCORD_WEBHOOK_URL
```

Discord 送信時は `allowed_mentions: {"parse": []}` を付け、AI 出力に `@everyone` などが混ざっても通知事故になりにくくしています。

## テスト

```bash
cd /home/aspa/agent-bus
PYTHONPATH=src python3 -m unittest discover -s tests
```
