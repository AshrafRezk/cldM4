#!/usr/bin/env bash
# Phase A proofs. Unit tests run anywhere. Live Ollama/Metal proofs run only on the Mini.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${CLOUDIATOR_DATA:-$HOME/Cloudiator}"
cd "$ROOT"

count_uvicorn() {
  # BSD pgrep (macOS) has no -c. GNU pgrep -fc is Linux-only.
  local pids
  pids="$(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo 0
    return
  fi
  echo "$pids" | wc -l | tr -d ' '
}

echo "== architecture =="
echo "uname -m: $(uname -m)  (Mini must be arm64)"
echo "uname -s: $(uname -s)  (Mini must be Darwin)"

echo
echo "== unit tests =="
cd "$ROOT/apps/worker"
if [[ -x .venv/bin/pytest ]]; then
  .venv/bin/pytest -q
elif command -v uv >/dev/null 2>&1; then
  uv sync --extra dev
  uv run pytest -q
else
  echo "skip pytest: install uv and run: cd apps/worker && uv sync --extra dev && uv run pytest -q"
fi

echo
echo "== live loopback (required on Darwin; skipped elsewhere unless 127.0.0.1:8080 is up) =="
wait_for_health() {
  local attempts="${1:-1}" i
  for i in $(seq 1 "$attempts"); do
    if curl -sf --max-time 2 http://127.0.0.1:8080/v1/health >/dev/null; then
      return 0
    fi
    [[ "$i" -lt "$attempts" ]] && sleep 2
  done
  return 1
}

HEALTH_ATTEMPTS=1
if [[ "$(uname -s)" == "Darwin" ]]; then
  HEALTH_ATTEMPTS=20
fi
if ! wait_for_health "$HEALTH_ATTEMPTS"; then
  echo "worker not listening on 127.0.0.1:8080"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "---- $DATA/logs/worker.err (last 50) ----"
    tail -n 50 "$DATA/logs/worker.err" 2>/dev/null || echo "(no worker.err yet)"
    echo
    echo "Start without a full reinstall (do not killall Ollama):"
    echo "  launchctl kickstart gui/\$(id -u)/ai.cloudiator.worker"
    echo "  curl -sS http://127.0.0.1:8080/v1/health"
    exit 1
  fi
  echo "skipped live loopback (not Darwin / worker not up)."
  exit 0
fi

command -v jq >/dev/null 2>&1 || { echo "install jq to pretty-print health"; true; }

echo "-- health --"
HEALTH="$(curl -sS http://127.0.0.1:8080/v1/health)"
echo "$HEALTH" | jq . 2>/dev/null || echo "$HEALTH"
echo "$HEALTH" | grep -qiE 'sk-cld|password|argon2|database_url' && {
  echo "FAIL: health JSON looks like it contains a secret"
  exit 1
}

echo "-- X-Request-Id --"
curl -sD- -o /dev/null http://127.0.0.1:8080/v1/health | grep -i x-request-id

echo "-- bind --"
if command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP:8080 -sTCP:LISTEN || true
fi

echo "uvicorn processes: $(count_uvicorn)  (must be 1 on the Mini)"

DEFAULT_MODEL="${DEFAULT_MODEL:-qwen3.5:9b}"
if curl -sf --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "-- chat --"
  curl -sS http://127.0.0.1:8080/v1/chat/completions \
    -H 'content-type: application/json' \
    -d "{\"model\":\"${DEFAULT_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"max_tokens\":16}" \
    | jq .choices[0].message 2>/dev/null || true
  echo "-- embeddings --"
  curl -sS http://127.0.0.1:8080/v1/embeddings \
    -H 'content-type: application/json' \
    -d '{"model":"nomic-embed-text","input":"hello"}' | jq '.data[0].embedding | length' 2>/dev/null || true
  echo "-- ollama ps (at most one generative + nomic-embed-text) --"
  ollama ps || true
else
  echo "Ollama is not on 11434; skipped live chat."
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "-- swap (must be 0 used) --"
  sysctl vm.swapusage || true
fi

echo
echo "smoke-phase-a: unit tests passed. Complete the Mini live checks in docs/cursor-phases.md Phase A Prove it."
