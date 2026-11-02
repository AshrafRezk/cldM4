#!/usr/bin/env bash
# Install the 2-minute health ping LaunchAgent (docs/host-setup.md §10, next-steps §6).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LABEL="ai.cloudiator.health-ping"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

require_arm64_macos

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$PLIST_DEST"
  pass "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Cloudiator/logs" "$HOME/Library/LaunchAgents"
chmod +x "$ROOT/scripts/health-ping.sh"

sed -e "s|__HOME__|$HOME|g" -e "s|__REPO__|$ROOT|g" \
  "$ROOT/infra/launchd/$LABEL.plist" > "$PLIST_DEST"
if grep -q '__HOME__\|__REPO__\|/Users/REPLACE' "$PLIST_DEST"; then
  rm -f "$PLIST_DEST"
  die "placeholder survived in $PLIST_DEST"
fi

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DEST"
launchctl enable "gui/$UID/$LABEL"
pass "bootstrapped $LABEL (every 120s)"
info "test it: launchctl kickstart -k gui/$UID/ai.cloudiator.worker is not enough (2 failures needed); stop the worker for 5 minutes and watch ~/Cloudiator/logs/health-ping.log"
launchctl print "gui/$UID/$LABEL" | head -12
