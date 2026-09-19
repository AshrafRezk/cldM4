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
bootstrap_label() {
  local label="$1" plist="$2"
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  launchctl enable "gui/$UID_NUM/$label"
  launchctl kickstart -k "gui/$UID_NUM/$label"
}

bootstrap_label "ai.cloudiator.ollama-env" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.ollama-env.plist"
bootstrap_label "ai.cloudiator.worker" \
  "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist"

echo "Waiting for 127.0.0.1:8080 (lifespan warmup can take ~60s on first 9B load)..."
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
  launchctl print "gui/$UID_NUM/ai.cloudiator.worker" | head -40 >&2 || true
  echo "---- tail $DATA/logs/worker.err ----" >&2
  tail -n 80 "$DATA/logs/worker.err" >&2 || true
  echo "---- tail $DATA/logs/worker.log ----" >&2
  tail -n 40 "$DATA/logs/worker.log" >&2 || true
  exit 1
fi

launchctl print "gui/$UID_NUM/ai.cloudiator.worker" | head -20
echo
curl -sS http://127.0.0.1:8080/v1/health
echo
echo "LaunchAgent ai.cloudiator.worker installed and healthy on 127.0.0.1:8080."
