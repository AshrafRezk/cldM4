#!/usr/bin/env bash
# Install the worker LaunchAgent. Substitutes real paths for __HOME__/__REPO__/__USER__.
set -euo pipefail

abort() { echo "abort: $*" >&2; exit 1; }

UNAME_S="$(uname -s)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${CLOUDIATOR_DATA:-$HOME/Cloudiator}"
mkdir -p "$DATA/logs" "$HOME/Library/LaunchAgents"

RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT

render() {
  local src="$1" dest="$2" mode="${3:-}"
  sed \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__REPO__|$ROOT|g" \
    -e "s|__USER__|$USER|g" \
    -e "s|__DATA__|$DATA|g" \
    "$src" > "$dest"
  grep -q REPLACE "$dest" && abort "$dest still contains REPLACE"
  grep -q '__HOME__\|__REPO__\|__DATA__' "$dest" && abort "$dest still contains placeholders"
  if [[ -n "$mode" ]]; then
    chmod "$mode" "$dest"
  fi
}

render "$ROOT/infra/launchagents/run-worker.sh" "$DATA/run-worker.sh" 755
render "$ROOT/infra/launchagents/set-ollama-env.sh" "$DATA/set-ollama-env.sh" 755
render "$ROOT/infra/launchagents/ai.cloudiator.worker.plist" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist"
render "$ROOT/infra/launchagents/ai.cloudiator.ollama-env.plist" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.ollama-env.plist"

if [[ "$UNAME_S" != "Darwin" ]]; then
  echo "Not Darwin; wrote wrappers under $DATA and skipped launchctl."
  exit 0
fi

UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

# Never bootout by default. bootout + bootstrap error 5 left the worker
# unloaded ("Could not find service ai.cloudiator.worker") while uvicorn
# was SIGTERM'd. Plist/wrapper updates on disk apply on the next start;
# Python is loaded from ~/cldM4. Error 5 = already loaded.
ensure_agent() {
  local label="$1" plist="$2" required="${3:-0}"
  local target="$DOMAIN/$label"
  if launchctl print "$target" >/dev/null 2>&1; then
    echo "$label already loaded"
    launchctl enable "$target" 2>/dev/null || true
    return 0
  fi
  if ! launchctl bootstrap "$DOMAIN" "$plist" 2>/tmp/cloudiator-bootstrap.err; then
    if grep -qiE 'Input/output error|already loaded|Duplicate' /tmp/cloudiator-bootstrap.err 2>/dev/null; then
      echo "$label already loaded (bootstrap error 5); continuing"
    else
      echo "bootstrap $label:" >&2
      cat /tmp/cloudiator-bootstrap.err >&2 || true
      if [[ "$required" == "1" ]]; then
        abort "bootstrap $label failed"
      fi
      return 0
    fi
  fi
  launchctl enable "$target" 2>/dev/null || true
}

ensure_agent "ai.cloudiator.ollama-env" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.ollama-env.plist" 0
launchctl kickstart "$DOMAIN/ai.cloudiator.ollama-env" 2>/dev/null || true

ensure_agent "ai.cloudiator.worker" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist" 1

if curl -sf --max-time 1 http://127.0.0.1:8080/v1/health >/dev/null; then
  echo "worker already healthy on 127.0.0.1:8080; skipping kickstart"
else
  # Never kickstart -k: that SIGTERMs a healthy worker. Missing job needs
  # bootstrap (ensure_agent). Loaded-but-idle job needs kickstart only.
  launchctl kickstart "$DOMAIN/ai.cloudiator.worker" 2>/dev/null || true
fi

echo "Waiting for 127.0.0.1:8080..."
ok=0
for _ in $(seq 1 45); do
  if curl -sf --max-time 2 http://127.0.0.1:8080/v1/health >/dev/null; then
    ok=1
    break
  fi
  sleep 2
done
if [[ "$ok" -ne 1 ]]; then
  echo "abort: worker did not become healthy on 127.0.0.1:8080" >&2
  echo "---- launchctl print ----" >&2
  launchctl print "$DOMAIN/ai.cloudiator.worker" | head -40 >&2 || true
  echo "---- tail $DATA/logs/worker.err ----" >&2
  tail -n 80 "$DATA/logs/worker.err" >&2 || true
  echo "---- tail $DATA/logs/worker.log ----" >&2
  tail -n 40 "$DATA/logs/worker.log" >&2 || true
  exit 1
fi

launchctl print "$DOMAIN/ai.cloudiator.worker" | head -20
echo
curl -sS http://127.0.0.1:8080/v1/health
echo
echo "LaunchAgent ai.cloudiator.worker installed and healthy on 127.0.0.1:8080."
