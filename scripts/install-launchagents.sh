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

sed \
  -e "s|__HOME__|$HOME|g" \
  -e "s|__REPO__|$ROOT|g" \
  -e "s|__USER__|$USER|g" \
  -e "s|__DATA__|$DATA|g" \
  "$ROOT/infra/launchagents/run-worker.sh" > "$DATA/run-worker.sh"
chmod 755 "$DATA/run-worker.sh"
# Refuse to install a wrapper that still has placeholders.
grep -q REPLACE "$DATA/run-worker.sh" && abort "run-worker.sh still contains REPLACE"
grep -q '__HOME__\|__REPO__\|__DATA__' "$DATA/run-worker.sh" && abort "run-worker.sh still contains placeholders"

sed \
  -e "s|__HOME__|$HOME|g" \
  -e "s|__REPO__|$ROOT|g" \
  -e "s|__USER__|$USER|g" \
  -e "s|__DATA__|$DATA|g" \
  "$ROOT/infra/launchagents/ai.cloudiator.worker.plist" \
  > "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist"

grep -q REPLACE "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist" && abort "plist still contains REPLACE"
grep -q '__HOME__\|__REPO__\|__DATA__' "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist" && abort "plist still contains placeholders"

if [[ "$UNAME_S" != "Darwin" ]]; then
  echo "Not Darwin; wrote $DATA/run-worker.sh and skipped launchctl."
  exit 0
fi

UID_NUM="$(id -u)"
# Local Network permission: operator must have run the binary interactively once.
launchctl bootout "gui/$UID_NUM/ai.cloudiator.worker" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist"
launchctl enable "gui/$UID_NUM/ai.cloudiator.worker"
launchctl kickstart -k "gui/$UID_NUM/ai.cloudiator.worker"
launchctl print "gui/$UID_NUM/ai.cloudiator.worker" | head -20
echo "LaunchAgent ai.cloudiator.worker installed."
