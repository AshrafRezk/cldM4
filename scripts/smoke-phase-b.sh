#!/usr/bin/env bash
# Phase B definition of done (docs/cursor-phases.md "Prove it").
#
#   export SMOKE_API_KEY=sk-cld-<id>_<secret>  # a real key, minted with app.dbtool
#   scripts/smoke-phase-b.sh                   # loopback + public HTTPS checks
#   scripts/smoke-phase-b.sh --local           # loopback only; skip tunnel + public HTTPS
#
# It only reads. Non-zero exit means the phase is not done.
#
# Two checks this script cannot do for you, and they are the ones that matter:
#   1. Run the public HTTPS checks from a PHONE ON CELLULAR. From the Mini's own
#      network you may be testing your router's hairpin, not Cloudflare.
#   2. Import /tmp/cloudiator-oas.json into External Services in a dev org. The
#      shape checks below are necessary, not sufficient.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LOCAL="http://127.0.0.1:8080"
VENV_PY="$ROOT/apps/worker/.venv/bin/python"
CONFIG="$HOME/.cloudflared/config.yml"
TUNNEL_LABEL="com.cloudiator.cloudflared"

load_env_file "$HOME/Cloudiator/.env"
DEFAULT_MODEL="${DEFAULT_MODEL:-gemma4:e4b-it-qat}"
HOSTNAME_API="${TUNNEL_HOSTNAME:-api.cloudiator.org}"
PUBLIC="${PUBLIC_BASE_URL:-https://$HOSTNAME_API}"
KEY="${SMOKE_API_KEY:-}"
ONLY_LOCAL=0
[ "${1:-}" = "--local" ] && ONLY_LOCAL=1

json_field() {
  "$VENV_PY" -c '
import json,sys
data = json.load(sys.stdin)
for key in sys.argv[1].split("."):
    if isinstance(data, list):
        data = data[int(key)]
    else:
        data = data.get(key)
    if data is None:
        break
print(data)
' "$1" 2>/dev/null
}

printf '%sPhase B smoke%s  (%s, model %s)\n' "$C_BOLD" "$C_OFF" "$PUBLIC" "$DEFAULT_MODEL"

# --------------------------------------------------------------------------
section "Secrets stay out of git"

if [ -f "$HOME/Cloudiator/.env" ]; then
  pass "$HOME/Cloudiator/.env exists"
  PERMS="$(file_mode "$HOME/Cloudiator/.env")"
  [ "$PERMS" = "600" ] && pass ".env is chmod 600" || fail ".env is $PERMS: chmod 600 ~/Cloudiator/.env"
  case "$HOME/Cloudiator/.env" in
    "$ROOT"/*) fail ".env is inside the git working tree" ;;
    *)         pass ".env is outside the git working tree" ;;
  esac
else
  fail "no ~/Cloudiator/.env"
fi

if [ -n "${DATABASE_URL:-}" ]; then
  case "$DATABASE_URL" in
    *-pooler.*) pass "DATABASE_URL is the pooled Neon endpoint" ;;
    *)          fail "DATABASE_URL has no '-pooler' in the host (PLAN.md §11)" ;;
  esac
else
  fail "DATABASE_URL is not set"
fi

for name in CF_ACCESS_AUD CF_ACCESS_TEAM_DOMAIN; do
  eval "value=\${$name:-}"
  [ -n "$value" ] && pass "$name is set" || fail "$name is not set; /v1/admin/* cannot verify Access"
done

if git -C "$ROOT" ls-files --error-unmatch .env >/dev/null 2>&1; then
  fail ".env is tracked by git"
else
  pass "no .env tracked by git"
fi

# --------------------------------------------------------------------------
section "Neon schema"

if [ -n "${DATABASE_URL:-}" ] && [ -x "$VENV_PY" ]; then
  if (cd "$ROOT/apps/worker" && "$VENV_PY" -m app.dbtool verify-schema >/tmp/cloudiator-schema.log 2>&1); then
    pass "$(head -1 /tmp/cloudiator-schema.log)"
  else
    fail "$(head -2 /tmp/cloudiator-schema.log | tr '\n' ' ')"
  fi
  rm -f /tmp/cloudiator-schema.log
fi

# --------------------------------------------------------------------------
section "Loopback auth"

if [ -z "$KEY" ]; then
  warn "SMOKE_API_KEY is not set, so the authenticated checks are skipped. Mint one:"
  info "  cd apps/worker && .venv/bin/python -m app.dbtool mint-key \\"
  info "      --tenant cloudiator --name 'Phase B smoke' --preset salesforce_engineer"
else
  case "$KEY" in
    *…*|*'...'*)
      fail "SMOKE_API_KEY still has a placeholder ellipsis. Copy the whole minted line, including the secret after the underscore."
      KEY=""
      ;;
    sk-cld-*_*)
      KEY_SECRET="${KEY#*_}"
      if [ "${#KEY_SECRET}" -lt 32 ]; then
        fail "SMOKE_API_KEY secret is ${#KEY_SECRET} chars; a minted key is ~43. Copy the whole Shown-once line."
        KEY=""
      else
        pass "SMOKE_API_KEY looks like sk-cld-<id>_<secret>"
      fi
      ;;
    *)
      fail "SMOKE_API_KEY is not an sk-cld- key"
      KEY=""
      ;;
  esac
fi

check_status() {
  local label="$1" expect_status="$2" expect_code="$3" url="$4"
  shift 4
  local status code
  status="$(curl -s -o /tmp/cloudiator-smoke.json -w '%{http_code}' --max-time 120 "$url" "$@" 2>/dev/null)"
  code="$(json_field error.code < /tmp/cloudiator-smoke.json)"
  [ "$code" = "None" ] && code=""
  if [ "$status" = "$expect_status" ] && { [ -z "$expect_code" ] || [ "$code" = "$expect_code" ]; }; then
    pass "$label -> $status ${code:-ok}"
  else
    fail "$label -> $status ${code:-} (expected $expect_status ${expect_code:-})"
    head -c 200 /tmp/cloudiator-smoke.json
    printf '\n'
  fi
}

check_status "no key is a 401" 401 invalid_api_key "$LOCAL/v1/chat/completions" \
  -H 'content-type: application/json' -d '{}'
check_status "a garbage key is a 401" 401 invalid_api_key "$LOCAL/v1/chat/completions" \
  -H 'Authorization: Bearer sk-cld-nope_nope' -H 'content-type: application/json' -d '{}'
check_status "health needs no key" 200 "" "$LOCAL/v1/health"
check_status "admin needs Access" 403 scope_denied "$LOCAL/v1/admin/cache/flush" -X POST

if [ -n "${ADMIN_TOKEN:-}" ]; then
  check_status "loopback break-glass works" 200 "" "$LOCAL/v1/admin/cache/flush" \
    -X POST -H "X-Admin-Token: $ADMIN_TOKEN"
  check_status "break-glass is refused through the tunnel" 403 scope_denied \
    "$LOCAL/v1/admin/cache/flush" -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H 'Cf-Connecting-Ip: 203.0.113.7'
fi

if [ -n "$KEY" ]; then
  check_status "a real key can chat" 200 "" "$LOCAL/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
    -d "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"stream\":false,\"max_tokens\":16}"
  check_status "an out-of-scope model is a 403" 403 scope_denied "$LOCAL/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
    -d '{"model":"gpt-oss:20b","messages":[{"role":"user","content":"hi"}]}'
fi
rm -f /tmp/cloudiator-smoke.json

# --------------------------------------------------------------------------
section "Usage outbox and db state"

HEALTH="$(curl -fsS --max-time 5 "$LOCAL/v1/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
  fail "no answer from $LOCAL/v1/health"
else
  DB_STATE="$(printf '%s' "$HEALTH" | json_field db)"
  DEPTH="$(printf '%s' "$HEALTH" | json_field outbox_depth)"
  info "db=$DB_STATE outbox_depth=$DEPTH"
  case "$DB_STATE" in
    ok)             pass "db = ok" ;;
    unknown)        warn "db = unknown (nothing has queried Neon since boot)" ;;
    degraded)       fail "db = degraded — Neon is unreachable; chat still works, usage is queued" ;;
    not_configured) fail "db = not_configured — DATABASE_URL is missing from the worker env" ;;
    *)              fail "db = $DB_STATE" ;;
  esac
  [ "$DEPTH" = "0" ] && pass "outbox is empty" || warn "outbox depth is $DEPTH (it drains every 10s)"
  if printf '%s' "$HEALTH" | grep -qiE 'sk-cld|postgres|password|secret|argon2|/Users/'; then
    fail "the health body leaks something it should not"
  else
    pass "no secrets in the health body"
  fi
fi

# The Neon-down drill is destructive-ish, so it stays a documented manual step.
info "Neon-down drill (manual): block the Neon host, chat again with the same key,"
info "  then check health: db becomes degraded, outbox_depth grows, chat keeps returning 200."
info "  Unblock, wait ~15s, and the depth returns to 0 with rows in usage_events."

# 11434 must never leave loopback, with or without a tunnel.
OLLAMA_BIND="$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u)"
if [ -n "$OLLAMA_BIND" ] && printf '%s\n' "$OLLAMA_BIND" | grep -qv '^127\.0\.0\.1:\|^\[::1\]:'; then
  fail "11434 is bound beyond loopback ($OLLAMA_BIND)"
else
  pass "11434 is loopback only"
fi

if [ "$ONLY_LOCAL" = "1" ]; then
  info "--local: skipping named-tunnel and public HTTPS checks. Run scripts/install-tunnel.sh next."
  summary "Phase B smoke (local only)"
  exit $?
fi

# --------------------------------------------------------------------------
section "Tunnel configuration"

if [ -f "$CONFIG" ]; then
  pass "$CONFIG exists"
  [ "$(grep -c 11434 "$CONFIG")" = "0" ] \
    && pass "11434 does not appear in the ingress" \
    || fail "11434 IS IN THE INGRESS. Rotate every sk-cld- key and assume the models were used by strangers"
  grep -q 'service: http://127.0.0.1:8080' "$CONFIG" \
    && pass "the origin is http://127.0.0.1:8080" \
    || fail "the origin is not 127.0.0.1:8080"
  [ "$(grep -c 'service: http://' "$CONFIG")" = "1" ] \
    && pass "exactly one http origin" \
    || fail "more than one http origin in the ingress"
  grep -q '^no-autoupdate: true' "$CONFIG" \
    && pass "no-autoupdate: true" \
    || fail "no-autoupdate is not true"
  grep -q '^tunnel: [0-9a-f-]\{36\}$' "$CONFIG" \
    && pass "a named tunnel UUID is configured (not a quick tunnel)" \
    || fail "no named tunnel UUID in the config"
  grep -qi 'trycloudflare' "$CONFIG" \
    && fail "a quick tunnel hostname is in the config" \
    || pass "no quick tunnel"
else
  fail "no $CONFIG. Run scripts/install-tunnel.sh"
fi

if launchctl print "gui/$UID/$TUNNEL_LABEL" >/tmp/cloudiator-tunnel.log 2>&1; then
  grep -q "state = running" /tmp/cloudiator-tunnel.log \
    && pass "$TUNNEL_LABEL state = running" \
    || fail "$TUNNEL_LABEL is loaded but not running"
else
  fail "$TUNNEL_LABEL is not loaded. Run scripts/install-tunnel.sh"
fi
rm -f /tmp/cloudiator-tunnel.log

# --------------------------------------------------------------------------
section "Public HTTPS (run this from a phone on cellular too)"

# A non-browser User-Agent proves the WAF skip rule: Apex is not a browser and
# cannot answer a challenge, so an HTML interstitial here is a Phase F outage.
PUBLIC_HEALTH_BODY=/tmp/cloudiator-public-health.txt
PUBLIC_STATUS="$(curl -s -A 'Salesforce/1.0' -o "$PUBLIC_HEALTH_BODY" -w '%{http_code}' \
  --max-time 15 "$PUBLIC/v1/health" 2>/dev/null)"
if [ "$PUBLIC_STATUS" = "200" ]; then
  pass "GET $PUBLIC/v1/health is 200 with a non-browser User-Agent"
else
  fail "GET $PUBLIC/v1/health is $PUBLIC_STATUS"
fi
if head -c 200 "$PUBLIC_HEALTH_BODY" | grep -qi '<!doctype html\|<html'; then
  fail "Cloudflare answered with HTML. Bot Fight Mode / BIC / a challenge is on (operator-checklist §2a)"
else
  pass "the body is JSON, not a Cloudflare interstitial"
fi
rm -f "$PUBLIC_HEALTH_BODY"

BAD=/tmp/cloudiator-bad.txt
BAD_STATUS="$(curl -s -o "$BAD" -w '%{http_code}' --max-time 15 "$PUBLIC/v1/chat/completions" \
  -H 'Authorization: Bearer sk-cld-nope_nope' -H 'content-type: application/json' -d '{}' 2>/dev/null)"
if [ "$BAD_STATUS" = "401" ] && head -c 20 "$BAD" | grep -q '{"error"'; then
  pass "a bad key over HTTPS is a JSON 401 from FastAPI"
else
  fail "a bad key over HTTPS gave $BAD_STATUS: $(head -c 120 "$BAD")"
  info "if that is HTML, the WAF is eating the request before the worker sees it"
fi
rm -f "$BAD"

if curl -s --max-time 5 "https://$HOSTNAME_API:11434/api/tags" >/dev/null 2>&1; then
  fail "something answered on $HOSTNAME_API:11434"
else
  pass "11434 is not reachable over the WAN"
fi

if [ -n "$KEY" ]; then
  CHAT=/tmp/cloudiator-public-chat.json
  CHAT_STATUS="$(curl -s -o "$CHAT" -w '%{http_code}' --max-time 120 "$PUBLIC/v1/chat/completions" \
    -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
    -d "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"max_tokens\":16}" \
    2>/dev/null)"
  if [ "$CHAT_STATUS" = "200" ]; then
    pass "chat over HTTPS with a real key: $(json_field choices.0.message.content < "$CHAT" | head -c 60)"
  else
    fail "chat over HTTPS gave $CHAT_STATUS: $(head -c 200 "$CHAT")"
  fi
  REQ_ID="$(curl -sD- -o /dev/null --max-time 15 "$PUBLIC/v1/health" 2>/dev/null | grep -ic '^x-request-id:')"
  [ "$REQ_ID" = "1" ] && pass "X-Request-Id survives the tunnel" || fail "no X-Request-Id through the tunnel"
  rm -f "$CHAT"

  # ---------------------------------------------------------------------
  section "Salesforce OpenAPI"

  OAS=/tmp/cloudiator-oas.json
  if curl -fsS --max-time 30 "$PUBLIC/v1/openapi.json?target=salesforce" \
      -H "Authorization: Bearer $KEY" -o "$OAS" 2>/dev/null; then
    pass "downloaded the Salesforce document"
    if "$VENV_PY" - "$OAS" >/tmp/cloudiator-oas-report.txt 2>&1 <<'PY'
import json, re, sys

doc = json.load(open(sys.argv[1]))
problems = []
if doc.get("openapi") != "3.0.3":
    problems.append(f"openapi is {doc.get('openapi')!r}, expected 3.0.3")

def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("oneOf", "anyOf", "allOf", "not"):
                problems.append(f"composition keyword {key} at {path}")
            if key == "additionalProperties":
                problems.append(f"free-form additionalProperties at {path}")
            if key == "$ref" and not str(value).startswith("#/"):
                problems.append(f"external $ref at {path}: {value}")
            if key == "format" and value == "binary":
                problems.append(f"format: binary at {path}")
            walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            walk(item, f"{path}[{index}]")

walk(doc)

ids = [
    operation["operationId"]
    for item in doc.get("paths", {}).values()
    for operation in item.values()
    if isinstance(operation, dict) and "operationId" in operation
]
if len(ids) != len(set(ids)):
    problems.append("operationId values are not unique")
for oid in ids:
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", oid):
        problems.append(f"operationId is not Apex-safe: {oid}")
for item in doc.get("paths", {}).values():
    for operation in item.values():
        if not isinstance(operation, dict):
            continue
        bodies = [operation.get("requestBody") or {}]
        bodies += list((operation.get("responses") or {}).values())
        for body in bodies:
            for media in (body.get("content") or {}):
                if media != "application/json":
                    problems.append(f"media type {media}")

if problems:
    print("\n".join(f"  {problem}" for problem in problems))
    sys.exit(1)
print(f"  {len(ids)} operations, all importable: {', '.join(sorted(doc['paths']))}")
PY
    then
      pass "the document is the restricted 3.0.3 subset"
    else
      fail "the document would not import cleanly:"
    fi
    cat /tmp/cloudiator-oas-report.txt
    rm -f /tmp/cloudiator-oas-report.txt
    info "now import $OAS into External Services in a dev org. That is the real test."
  else
    fail "could not download $PUBLIC/v1/openapi.json?target=salesforce"
  fi
fi

section "Still yours to do by hand"
info "1. Repeat the public checks from a phone on cellular (not this Mini's network)."
info "2. Import the OAS into External Services in a dev org."
info "3. Run the Neon-down drill above."

summary "Phase B smoke"
