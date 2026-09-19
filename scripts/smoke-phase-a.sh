#!/usr/bin/env bash
# Phase A definition of done (docs/cursor-phases.md "Prove it").
#
# Run this on the Mac Mini with the worker running. It only reads; it starts
# nothing and installs nothing. Non-zero exit means the phase is not done.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BASE="http://127.0.0.1:8080"
VENV_PY="$ROOT/apps/worker/.venv/bin/python"
LABEL="ai.cloudiator.worker"

load_env_file "$HOME/Cloudiator/.env"
DEFAULT_MODEL="${DEFAULT_MODEL:-qwen3.5:9b}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

# Read one field out of a JSON body without requiring jq.
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

printf '%sPhase A smoke%s  (model: %s)\n' "$C_BOLD" "$C_OFF" "$DEFAULT_MODEL"

# --------------------------------------------------------------------------
section "Architecture"

[ "$(uname -m)" = "arm64" ] && pass "uname -m = arm64" || fail "uname -m = $(uname -m)"

if [ -x "$VENV_PY" ]; then
  MACHINE="$("$VENV_PY" -c 'import platform;print(platform.machine())')"
  [ "$MACHINE" = "arm64" ] && pass "venv python is arm64" || fail "venv python is $MACHINE"
else
  die "no venv at $VENV_PY. Run scripts/mac-setup.sh"
fi

# --------------------------------------------------------------------------
section "Single process, loopback only"

WORKERS="$(pgrep -fc "uvicorn app.main:app" 2>/dev/null || echo 0)"
if [ "$WORKERS" = "1" ]; then
  pass "exactly one uvicorn worker"
else
  fail "$WORKERS uvicorn workers. metal_lock is in-process: a second worker is a second scheduler"
fi

BINDINGS="$(lsof -nP -iTCP:8080 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u)"
if [ -z "$BINDINGS" ]; then
  fail "nothing is listening on 8080"
elif printf '%s\n' "$BINDINGS" | grep -q '^\*:8080\|^0\.0\.0\.0:8080'; then
  fail "8080 is bound to $BINDINGS — the tunnel must be the only ingress"
else
  pass "8080 bound to $BINDINGS"
fi

OLLAMA_BIND="$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u)"
if [ -n "$OLLAMA_BIND" ] && printf '%s\n' "$OLLAMA_BIND" | grep -qv '^127\.0\.0\.1:\|^\[::1\]:'; then
  fail "11434 is bound beyond loopback ($OLLAMA_BIND). Rotate every sk-cld- key"
else
  pass "11434 is loopback only"
fi

# --------------------------------------------------------------------------
section "GET /v1/health"

HEALTH="$(curl -fsS --max-time 5 "$BASE/v1/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
  fail "no answer from $BASE/v1/health"
else
  printf '%s\n' "$HEALTH" | (command -v jq >/dev/null 2>&1 && jq . || cat)
  [ "$(printf '%s' "$HEALTH" | json_field ok)" = "True" ] \
    && pass "ok = true" \
    || fail "ok is not true — read the degraded list above"
  for field in free_mb loaded queue_depth pressure free_disk_gb db version; do
    printf '%s' "$HEALTH" | grep -q "\"$field\"" && pass "reports $field" || fail "missing $field"
  done
  # Health is unauthenticated and local-only: no secrets, no key hashes.
  if printf '%s' "$HEALTH" | grep -qiE 'sk-cld|postgres|password|secret|argon2|/Users/'; then
    fail "health body leaks something it should not"
  else
    pass "no secrets in the health body"
  fi
fi

REQ_ID="$(curl -sD- -o /dev/null --max-time 5 "$BASE/v1/health" 2>/dev/null | grep -i '^x-request-id:' | tr -d '\r')"
[ -n "$REQ_ID" ] && pass "X-Request-Id present ($REQ_ID)" || fail "no X-Request-Id header"

ERR_REQ_ID="$(curl -sD- -o /dev/null --max-time 5 -X POST "$BASE/v1/chat/completions" \
  -H 'content-type: application/json' -d '{"messages":[{"role":"user","content":"hi"}],"n":4}' \
  2>/dev/null | grep -ic '^x-request-id:')"
[ "$ERR_REQ_ID" = "1" ] && pass "X-Request-Id present on errors too" || fail "errors carry no X-Request-Id"

# --------------------------------------------------------------------------
section "GET /v1/models — built from live ollama tags"

MODELS="$(curl -fsS --max-time 10 "$BASE/v1/models" 2>/dev/null)"
if [ -z "$MODELS" ]; then
  fail "no answer from /v1/models"
else
  if printf '%s' "$MODELS" | grep -q "\"$DEFAULT_MODEL\""; then
    pass "/v1/models lists $DEFAULT_MODEL"
  else
    fail "/v1/models does not list $DEFAULT_MODEL"
  fi
  if printf '%s' "$MODELS" | grep -q 'gpt-oss:20b'; then
    fail "/v1/models advertises gpt-oss:20b. A caller selecting it starts a 14 GB download inside a request"
  else
    pass "no Phase E model advertised"
  fi
fi

# --------------------------------------------------------------------------
section "POST /v1/chat/completions"

CHAT="$(curl -fsS --max-time 120 "$BASE/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":16}" \
  2>/dev/null)"
if [ -z "$CHAT" ]; then
  fail "chat returned nothing"
else
  CONTENT="$(printf '%s' "$CHAT" | json_field choices.0.message.content)"
  if [ -n "$CONTENT" ] && [ "$CONTENT" != "None" ]; then
    pass "chat replied: $(printf '%s' "$CONTENT" | head -c 60)"
  else
    fail "chat had no message content: $(printf '%s' "$CHAT" | head -c 200)"
  fi
  [ "$(printf '%s' "$CHAT" | json_field object)" = "chat.completion" ] \
    && pass "response object is chat.completion" || fail "response is not OpenAI-shaped"
  [ "$(printf '%s' "$CHAT" | json_field model)" = "$DEFAULT_MODEL" ] \
    && pass "response reports the real model" || warn "response model differs from the request"
fi

# --------------------------------------------------------------------------
section "POST /v1/embeddings"

EMB="$(curl -fsS --max-time 30 "$BASE/v1/embeddings" \
  -H 'content-type: application/json' \
  -d "{\"model\":\"$EMBED_MODEL\",\"input\":[\"hello\",\"world\"]}" 2>/dev/null)"
if printf '%s' "$EMB" | grep -q '"embedding"'; then
  pass "embeddings returned vectors"
else
  fail "embeddings failed: $(printf '%s' "$EMB" | head -c 200)"
fi

# --------------------------------------------------------------------------
section "Guards fail loudly"

check_code() {
  local label="$1" expect_status="$2" expect_code="$3" path="$4" body="$5"
  local out status code
  out="$(curl -s -o /tmp/cloudiator-smoke.json -w '%{http_code}' --max-time 30 \
    "$BASE$path" -H 'content-type: application/json' -d "$body" 2>/dev/null)"
  status="$out"
  code="$(json_field error.code < /tmp/cloudiator-smoke.json)"
  if [ "$status" = "$expect_status" ] && [ "$code" = "$expect_code" ]; then
    pass "$label → $status $code"
  else
    fail "$label → $status $code (expected $expect_status $expect_code)"
  fi
}

check_code "n=2 rejected"            400 not_supported            /v1/chat/completions \
  "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"n\":2}"
check_code "logit_bias rejected"     400 not_supported            /v1/chat/completions \
  "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"logit_bias\":{\"1\":1}}"
check_code "unknown model is a 404"  404 model_not_found          /v1/chat/completions \
  '{"model":"gpt-oss:20b","messages":[{"role":"user","content":"hi"}]}'
check_code "oversized prompt"        400 context_length_exceeded  /v1/chat/completions \
  "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"$(printf 'word %.0s' $(seq 1 6000))\"}]}"
check_code "http image_url blocked"  400 url_not_allowed          /v1/chat/completions \
  "{\"model\":\"$DEFAULT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"image_url\",\"image_url\":{\"url\":\"http://169.254.169.254/latest/meta-data/\"}}]}]}"
check_code "assistants never exist"  404 not_supported            /v1/assistants '{}'
rm -f /tmp/cloudiator-smoke.json

# --------------------------------------------------------------------------
section "RAM discipline"

if command -v ollama >/dev/null 2>&1; then
  ollama ps
  RESIDENT="$(ollama ps 2>/dev/null | awk 'NR>1{print $1}')"
  GEN=0
  for name in $RESIDENT; do
    case "$name" in
      "$EMBED_MODEL"|"$EMBED_MODEL":latest|nomic-embed-text|nomic-embed-text:latest) ;;
      *) GEN=$((GEN + 1)) ;;
    esac
  done
  if [ "$GEN" -le 1 ]; then
    pass "$GEN generative model resident (the embedder alongside it is expected)"
  else
    fail "$GEN generative models resident. That is a phase failure, not a warning"
  fi
fi

SWAP="$(sysctl -n vm.swapusage 2>/dev/null)"
info "vm.swapusage: $SWAP"
case "$SWAP" in
  *"used = 0.00M"*) pass "swap used = 0.00M" ;;
  *)                fail "swap is in use. Reduce the configuration — do not proceed (PLAN.md §4)" ;;
esac

# --------------------------------------------------------------------------
section "Tests and LaunchAgent"

if (cd "$ROOT/apps/worker" && .venv/bin/pytest -q >/tmp/cloudiator-pytest.log 2>&1); then
  pass "pytest green ($(tail -1 /tmp/cloudiator-pytest.log | tr -d '\n'))"
else
  fail "pytest failed:"
  tail -20 /tmp/cloudiator-pytest.log
fi

if launchctl print "gui/$UID/$LABEL" >/tmp/cloudiator-launchctl.log 2>&1; then
  head -20 /tmp/cloudiator-launchctl.log
  if grep -q "state = running" /tmp/cloudiator-launchctl.log; then
    pass "$LABEL state = running"
  else
    fail "$LABEL is loaded but not running"
  fi
  if grep -q "last exit status = 0" /tmp/cloudiator-launchctl.log; then
    pass "last exit status = 0"
  fi
else
  fail "$LABEL is not loaded. Run scripts/install-launchagents.sh"
fi

summary "Phase A smoke"
