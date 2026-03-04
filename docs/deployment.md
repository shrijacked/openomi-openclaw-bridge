# Deployment Runbook: Omi -> OpenClaw Bridge

This runbook documents how to containerize, deploy, verify, and operate the bridge in production.

## 1) Scope and Goal

- Goal: expose `POST /omi/chat-tools/openclaw` over public HTTPS for Omi Chat Tools.
- Gateway dependency: OpenClaw `POST /tools/invoke`.
- Reliability target: fast failure on bad config, clear health checks, reversible deploys.

## 2) Dependency Graph

```mermaid
graph TD
    A[Omi Chat Tool] --> B[Bridge Service]
    B --> C[OpenClaw Gateway]
    C --> D[Tool Runtime]
    E[Render Platform] --> B
    F[Env Vars and Secrets] --> B
```

## 3) Runtime Architecture

```mermaid
flowchart LR
    O[Omi] -->|HTTPS POST| W[Bridge /omi/chat-tools/openclaw]
    W -->|Auth check| V[Token Validator]
    V -->|ok| M[Payload Mapper]
    M -->|POST /tools/invoke| G[OpenClaw Gateway]
    G --> R[Tool Result]
    R --> N[Normalized Response]
    N --> O
```

## 4) Build and Run Locally (Docker)

From repo root:

```bash
docker build -t openomi-openclaw-bridge:local .
docker run --rm -p 8080:8080 \
  -e OPENCLAW_BASE_URL="https://gateway.yourdomain.com" \
  -e OPENCLAW_DEFAULT_TOOL="tools.search" \
  -e OPENCLAW_API_KEY="your-openclaw-key" \
  -e OMI_WEBHOOK_TOKEN="your-omi-webhook-token" \
  -e OPENCLAW_TIMEOUT_SECONDS="20" \
  openomi-openclaw-bridge:local
```

Health check:

```bash
curl -sS http://127.0.0.1:8080/healthz
```

Webhook smoke test:

```bash
curl -sS -X POST http://127.0.0.1:8080/omi/chat-tools/openclaw \
  -H "Authorization: Bearer your-omi-webhook-token" \
  -H "Content-Type: application/json" \
  -d '{
    "openclaw_tool": "tools.search",
    "arguments": {"query": "latest standup notes"},
    "session_id": "session-001"
  }'
```

## 5) Deploy to Render

`render.yaml` is included in repo root and defines:

- Docker runtime using `Dockerfile`
- Health check path `/healthz`
- Required secret env vars (manual set)

### Steps

1. Open Render dashboard -> New -> Blueprint.
2. Connect this GitHub repo.
3. Render reads `render.yaml` and creates service `openomi-openclaw-bridge`.
4. Set secret env vars in Render:
   - `OPENCLAW_BASE_URL`
   - `OPENCLAW_DEFAULT_TOOL`
   - `OPENCLAW_API_KEY`
   - `OMI_WEBHOOK_TOKEN`
5. Deploy and wait for health check to pass.

### API-driven deploy (automated)

If you prefer CLI/API automation instead of Dashboard clicks, use:

- `scripts/deploy_render.sh`

Required env vars:

- `RENDER_API_KEY`
- `OPENCLAW_BASE_URL`
- `OPENCLAW_DEFAULT_TOOL`
- `OMI_WEBHOOK_TOKEN`

Optional env vars:

- `OPENCLAW_API_KEY`
- `RENDER_OWNER_ID` (auto-detected when omitted)
- `RENDER_SERVICE_NAME` (default `openomi-openclaw-bridge`)
- `RENDER_REPO_URL` (defaults to git `origin` URL)
- `RENDER_REPO_BRANCH` (default `main`)
- `RENDER_PLAN` (default `free`)
- `RENDER_REGION` (default `oregon`)

Example:

```bash
export RENDER_API_KEY="rdr_..."
export OPENCLAW_BASE_URL="https://gateway.yourdomain.com"
export OPENCLAW_DEFAULT_TOOL="tools.search"
export OPENCLAW_API_KEY="your-openclaw-key"
export OMI_WEBHOOK_TOKEN="your-omi-webhook-token"
./scripts/deploy_render.sh
```

## 6) Configure Omi Chat Tool

Set webhook URL in Omi:

- `POST https://<render-service-domain>/omi/chat-tools/openclaw`

Set auth header in Omi (recommended):

- `Authorization: Bearer <OMI_WEBHOOK_TOKEN>`

## 7) Production Verification Checklist

- [ ] `GET /healthz` returns `200 {"status":"ok"}`
- [ ] Unauthorized webhook request returns `401`
- [ ] Authorized webhook request returns `200` with `status=ok`
- [ ] OpenClaw tool invocation succeeds for at least one real query
- [ ] Omi chat confirms tool output is returned to user

Automated smoke test:

```bash
export BRIDGE_BASE_URL="https://<your-render-domain>"
export OMI_WEBHOOK_TOKEN="your-omi-webhook-token"
export OPENCLAW_TOOL="tools.search"
export TEST_QUERY="find the latest standup notes"
./scripts/smoke_test.sh
```

## 8) Failure Modes and Actions

- 400 validation error:
  - Check payload format from Omi (`JSON object`, tool name present).
- 401 unauthorized:
  - Verify Omi header token equals `OMI_WEBHOOK_TOKEN`.
- 502 openclaw gateway error:
  - Verify `OPENCLAW_BASE_URL`, `OPENCLAW_API_KEY`, and gateway uptime.
- 500 internal error:
  - Inspect runtime logs for request payload and exception path.

## 9) Rollback Strategy

- Render: rollback to previous successful deploy from deployment history.
- If config-induced outage:
  - Restore last known-good env var values.
  - Redeploy previous image.

## 10) Traceability Map

- Container packaging: [Dockerfile](../Dockerfile)
- Build context hygiene: [.dockerignore](../.dockerignore)
- Platform deployment config: [render.yaml](../render.yaml)
- Automated Render deployment: [scripts/deploy_render.sh](../scripts/deploy_render.sh)
- Automated smoke tests: [scripts/smoke_test.sh](../scripts/smoke_test.sh)
- Runtime server: [server.py](../src/omi_openclaw_bridge/server.py)
- Gateway client validation: [bridge.py](../src/omi_openclaw_bridge/bridge.py)
- Regression tests: [test_bridge.py](../tests/test_bridge.py), [test_server.py](../tests/test_server.py)
