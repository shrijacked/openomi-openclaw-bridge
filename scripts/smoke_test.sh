#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[smoke-test] %s\n' "$*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log "Missing required command: $cmd"
    exit 1
  fi
}

require_env() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    log "Missing required environment variable: $var_name"
    exit 1
  fi
}

require_cmd curl
require_cmd jq

require_env BRIDGE_BASE_URL
require_env OMI_WEBHOOK_TOKEN

OPENCLAW_TOOL="${OPENCLAW_TOOL:-tools.search}"
TEST_QUERY="${TEST_QUERY:-health verification}"

bridge_base="${BRIDGE_BASE_URL%/}"

log "Checking health endpoint"
health_response="$(curl -fsS "${bridge_base}/healthz")"
printf '%s\n' "$health_response" | jq .

log "Checking unauthorized access handling"
unauthorized_status="$(
  curl -sS -o /tmp/openomi_smoke_unauthorized.json -w "%{http_code}" \
    -X POST "${bridge_base}/omi/chat-tools/openclaw" \
    -H "Content-Type: application/json" \
    -d '{"arguments":{"query":"unauthorized-check"}}'
)"
if [[ "$unauthorized_status" != "401" ]]; then
  log "Expected 401 for unauthorized request, got ${unauthorized_status}"
  cat /tmp/openomi_smoke_unauthorized.json
  exit 1
fi

log "Calling authorized webhook"
authorized_status="$(
  curl -sS -o /tmp/openomi_smoke_authorized.json -w "%{http_code}" \
    -X POST "${bridge_base}/omi/chat-tools/openclaw" \
    -H "Authorization: Bearer ${OMI_WEBHOOK_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg tool "$OPENCLAW_TOOL" --arg query "$TEST_QUERY" --arg session_id "smoke-session-001" '{openclaw_tool:$tool, arguments:{query:$query}, session_id:$session_id}')"
)"
if [[ "$authorized_status" != "200" ]]; then
  log "Expected 200 for authorized request, got ${authorized_status}"
  cat /tmp/openomi_smoke_authorized.json
  exit 1
fi

log "Authorized webhook response"
cat /tmp/openomi_smoke_authorized.json | jq .

rm -f /tmp/openomi_smoke_unauthorized.json /tmp/openomi_smoke_authorized.json
log "Smoke test completed successfully."
