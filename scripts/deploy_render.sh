#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${RENDER_API_BASE_URL:-https://api.render.com/v1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '[deploy-render] %s\n' "$*"
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

urlencode() {
  jq -nr --arg v "$1" '$v|@uri'
}

api_request() {
  local method="$1"
  local path="$2"
  local body_file="${3:-}"

  local response_file
  response_file="$(mktemp)"

  local http_code
  if [[ -n "$body_file" ]]; then
    http_code="$(
      curl -sS -o "$response_file" -w "%{http_code}" \
        -X "$method" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        -H "Content-Type: application/json" \
        "${API_BASE_URL}${path}" \
        --data-binary "@${body_file}"
    )"
  else
    http_code="$(
      curl -sS -o "$response_file" -w "%{http_code}" \
        -X "$method" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        "${API_BASE_URL}${path}"
    )"
  fi

  if [[ "$http_code" != 2* ]]; then
    log "Render API ${method} ${path} failed with status ${http_code}"
    cat "$response_file"
    rm -f "$response_file"
    exit 1
  fi

  cat "$response_file"
  rm -f "$response_file"
}

normalize_repo_url() {
  local repo="$1"
  if [[ "$repo" =~ ^git@github.com:(.*)\.git$ ]]; then
    printf 'https://github.com/%s\n' "${BASH_REMATCH[1]}"
    return
  fi
  if [[ "$repo" =~ ^https://github.com/.+\.git$ ]]; then
    printf '%s\n' "${repo%.git}"
    return
  fi
  printf '%s\n' "$repo"
}

require_cmd curl
require_cmd jq

require_env RENDER_API_KEY
require_env OPENCLAW_BASE_URL
require_env OPENCLAW_DEFAULT_TOOL
require_env OMI_WEBHOOK_TOKEN

if [[ -z "${RENDER_OWNER_ID:-}" ]]; then
  log "RENDER_OWNER_ID not set; discovering from /owners"
  owners_json="$(api_request GET "/owners")"
  owner_count="$(printf '%s' "$owners_json" | jq -r 'length')"
  if [[ "$owner_count" == "0" ]]; then
    log "Could not determine owner ID. Set RENDER_OWNER_ID explicitly."
    exit 1
  fi
  if [[ "$owner_count" != "1" ]]; then
    log "Multiple Render owners detected. Set RENDER_OWNER_ID to avoid deploying to the wrong workspace."
    printf '%s\n' "$owners_json" | jq -r '.[] | (.owner // .) | "\(.id)\t\(.name)\t\(.type)"'
    exit 1
  fi
  RENDER_OWNER_ID="$(printf '%s' "$owners_json" | jq -r '.[0].owner.id // .[0].id // empty')"
fi

SERVICE_NAME="${RENDER_SERVICE_NAME:-openomi-openclaw-bridge}"
SERVICE_PLAN="${RENDER_PLAN:-free}"
SERVICE_REGION="${RENDER_REGION:-oregon}"
REPO_BRANCH="${RENDER_REPO_BRANCH:-main}"

REPO_URL="${RENDER_REPO_URL:-}"
if [[ -z "$REPO_URL" ]]; then
  require_cmd git
  REPO_URL="$(git -C "$ROOT_DIR" config --get remote.origin.url || true)"
fi
if [[ -z "$REPO_URL" ]]; then
  log "Could not determine repository URL. Set RENDER_REPO_URL explicitly."
  exit 1
fi
REPO_URL="$(normalize_repo_url "$REPO_URL")"

ENV_VARS_JSON="$(
  jq -n \
    --arg openclaw_base_url "$OPENCLAW_BASE_URL" \
    --arg openclaw_default_tool "$OPENCLAW_DEFAULT_TOOL" \
    --arg openclaw_api_key "${OPENCLAW_API_KEY:-}" \
    --arg omi_webhook_token "$OMI_WEBHOOK_TOKEN" \
    '
      [
        {"key":"HOST","value":"0.0.0.0"},
        {"key":"OPENCLAW_BASE_URL","value":$openclaw_base_url},
        {"key":"OPENCLAW_DEFAULT_TOOL","value":$openclaw_default_tool},
        {"key":"OMI_WEBHOOK_TOKEN","value":$omi_webhook_token},
        {"key":"OPENCLAW_TIMEOUT_SECONDS","value":"20"}
      ] + (
        if $openclaw_api_key == "" then
          []
        else
          [{"key":"OPENCLAW_API_KEY","value":$openclaw_api_key}]
        end
      )
    '
)"

log "Checking for existing Render service named '${SERVICE_NAME}'"
services_json="$(api_request GET "/services?ownerId=$(urlencode "$RENDER_OWNER_ID")&name=$(urlencode "$SERVICE_NAME")&limit=100")"
SERVICE_ID="$(printf '%s' "$services_json" | jq -r --arg name "$SERVICE_NAME" '[.[] | (.service // .)] | map(select(.name == $name)) | .[0].id // empty')"

if [[ -z "$SERVICE_ID" ]]; then
  log "No existing service found; creating web service"
  create_payload_file="$(mktemp)"
  jq -n \
    --arg owner_id "$RENDER_OWNER_ID" \
    --arg service_name "$SERVICE_NAME" \
    --arg repo "$REPO_URL" \
    --arg branch "$REPO_BRANCH" \
    --arg plan "$SERVICE_PLAN" \
    --arg region "$SERVICE_REGION" \
    --argjson env_vars "$ENV_VARS_JSON" \
    '
      {
        "type":"web_service",
        "name":$service_name,
        "ownerId":$owner_id,
        "repo":$repo,
        "autoDeploy":"yes",
        "branch":$branch,
        "envVars":$env_vars,
        "serviceDetails":{
          "env":"docker",
          "runtime":"docker",
          "healthCheckPath":"/healthz",
          "plan":$plan,
          "region":$region
        }
      }
    ' >"$create_payload_file"

  create_response="$(api_request POST "/services" "$create_payload_file")"
  rm -f "$create_payload_file"

  SERVICE_ID="$(printf '%s' "$create_response" | jq -r '.service.id // .id // empty')"
  if [[ -z "$SERVICE_ID" ]]; then
    log "Render returned no service ID after create."
    printf '%s\n' "$create_response"
    exit 1
  fi
else
  log "Found service id ${SERVICE_ID}; updating environment variables"
  env_payload_file="$(mktemp)"
  printf '%s\n' "$ENV_VARS_JSON" >"$env_payload_file"
  api_request PUT "/services/${SERVICE_ID}/env-vars" "$env_payload_file" >/dev/null
  rm -f "$env_payload_file"
fi

log "Triggering deploy"
deploy_payload_file="$(mktemp)"
printf '{"clearCache":"do_not_clear"}\n' >"$deploy_payload_file"
deploy_response="$(api_request POST "/services/${SERVICE_ID}/deploys" "$deploy_payload_file")"
rm -f "$deploy_payload_file"

service_response="$(api_request GET "/services/${SERVICE_ID}")"
service_url="$(printf '%s' "$service_response" | jq -r '.serviceDetails.url // empty')"
dashboard_url="$(printf '%s' "$service_response" | jq -r '.dashboardUrl // empty')"
deploy_id="$(printf '%s' "$deploy_response" | jq -r '.id // empty')"

log "Deploy requested successfully."
printf 'service_id=%s\n' "$SERVICE_ID"
printf 'service_url=%s\n' "$service_url"
printf 'dashboard_url=%s\n' "$dashboard_url"
printf 'deploy_id=%s\n' "$deploy_id"
