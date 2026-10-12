#!/usr/bin/env bash
# Install the nightly Neon retention LaunchAgent (docs/next-steps.md §3).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LABEL="ai.cloudiator.retention"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

require_arm64_macos

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$PLIST_DEST"
  pass "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Cloudiator/logs" "$HOME/Library/LaunchAgents"
chmod +x "$ROOT/scripts/run-neon-retention.sh"

sed -e "s|__HOME__|$HOME|g" -e "s|__REPO__|$ROOT|g" \
  "$ROOT/infra/launchd/$LABEL.plist" > "$PLIST_DEST"
if grep -q '__HOME__\|__REPO__\|/Users/REPLACE' "$PLIST_DEST"; then
  rm -f "$PLIST_DEST"
  die "placeholder survived in $PLIST_DEST"
fi

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DEST"
launchctl enable "gui/$UID/$LABEL"
pass "bootstrapped $LABEL (fires 03:15 local)"
info "prove once now: $ROOT/scripts/run-neon-retention.sh"
launchctl print "gui/$UID/$LABEL" | head -12
