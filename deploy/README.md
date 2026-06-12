# Agent Bus の公開

チームで使う場合は、Agent Bus を 1つの HTTPS Webサービスとして公開します。チームメンバーに渡す情報は基本的にこれだけです。

```text
AGENT_BUS_URL=https://your-agent-bus.example.com
AGENT_BUS_TOKEN=<shared-write-token>
AGENT_BUS_DEFAULT_PROJECT=<project-name>
```

HTTPS は Python アプリ内で処理せず、hosting layer に任せます。

## 認証

2層に分けるのが推奨です。

```text
人間のブラウザアクセス: Cloudflare Access / Google IAP / Caddy basic auth / provider auth
AI/API の書き込み: AGENT_BUS_TOKEN
```

推奨 environment:

```text
AGENT_BUS_TOKEN=<long random write token>
AGENT_BUS_READ_TOKEN=<optional read-only token>
AGENT_BUS_PUBLIC_READ=false
```

`AGENT_BUS_PUBLIC_READ=true` は、プロジェクト履歴を本当に公開してよい場合だけ使ってください。MCP client には `AGENT_BUS_TOKEN` を渡します。ブラウザ閲覧は、永続的な query string token を共有するより、Cloudflare Access などの前段認証を使う方が安全です。

token 生成:

```bash
openssl rand -hex 32
```

## どこで動かすか

### Option A: Managed Web Service

一番簡単です。Render、Railway、Fly.io などを使います。アプリは platform 内では HTTP で待ち受け、platform が HTTPS を提供します。

Render ではリポジトリ直下の `render.yaml` を Blueprint として使えます。Dashboard で `New > Blueprint` を選び、この repository を接続してください。

必要な environment:

```text
AGENT_BUS_HOST=0.0.0.0
AGENT_BUS_TOKEN=<long random token>
AGENT_BUS_READ_TOKEN=<optional read-only browser token>
AGENT_BUS_PUBLIC_READ=false
AGENT_BUS_DB=/data/agent-bus.sqlite3
AGENT_BUS_ARTIFACT_DIR=/data/artifacts
DISCORD_WEBHOOK_URL=<fallback webhook, optional>
```

SQLite を使う場合は `/data` に persistent disk を mount してください。

### Option B: VPS + Caddy + docker-compose

安く安定させるならこの構成です。

```text
Internet
  -> Caddy HTTPS
  -> agent-bus container :8765
  -> Docker volume / SQLite
```

`docker-compose.yml` を使い、Caddy 側で HTTPS と必要なら basic auth を設定します。

### Option C: 今のマシン + Cloudflare Tunnel

検証や短期運用に向いています。外向き firewall を開けずに HTTPS URL を作れます。

サーバ:

```bash
export AGENT_BUS_HOST=127.0.0.1
export AGENT_BUS_PORT=8765
export AGENT_BUS_TOKEN="$(openssl rand -hex 32)"
/home/aspa/agent-bus/bin/agent-bus
```

tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

生成された `https://...trycloudflare.com` を `AGENT_BUS_URL` として使います。

## チームメンバーの接続

各メンバーはこれを実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/takatronix/agent-bus/main/scripts/team-connect.sh \
  | AGENT_BUS_URL=https://your-agent-bus.example.com \
    AGENT_BUS_TOKEN=<shared-write-token> \
    AGENT_BUS_DEFAULT_PROJECT=agent-bus \
    bash
```

script が設定するもの:

```text
Claude Code user MCP
Cursor global MCP
Codex MCP, if installed
```

実行後、AI client を reload してください。

## プロジェクト履歴 UI

ブラウザで開きます。

```text
https://your-agent-bus.example.com
```

`AGENT_BUS_PUBLIC_READ=false` で `AGENT_BUS_READ_TOKEN` を使う場合:

```text
https://your-agent-bus.example.com?read_token=<read-token>
```

プロジェクトページ:

```text
https://your-agent-bus.example.com/projects/<project-name>
```

プロジェクトページでは、概要、Discord webhook、タスク、イベント履歴を確認できます。Discord webhook URL は保存後も表示されません。
