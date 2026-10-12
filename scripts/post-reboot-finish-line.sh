#!/usr/bin/env bash
# Run on the Mac Mini AFTER reboot + unlock + login as the appliance user.
# Pulls merged Phase F, restarts the worker, installs Neon retention, proves health.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

require_arm64_macos
cd "$ROOT"

section "Git"
git fetch origin main
git checkout main
git pull origin main
pass "main at $(git rev-parse --short HEAD)"

section "Worker"
launchctl kickstart -k "gui/$UID/ai.cloudiator.worker" 2>/dev/null \
  || warn "kickstart failed — is ai.cloudiator.worker installed?"
sleep 3
HEALTH="$(/usr/bin/curl -sS --max-time 10 http://127.0.0.1:8080/v1/health || true)"
echo "$HEALTH" | /usr/bin/python3 -m json.tool || echo "$HEALTH"
echo "$HEALTH" | grep -q '"ok": true' && pass "health ok" || fail "health not ok — check swap/degraded"
echo "$HEALTH" | grep -q '"swap_used_mb": 0' && pass "swap cleared" \
  || warn "swap still non-zero — another reboot or quit heavy apps"

section "Neon retention"
mkdir -p "$HOME/Cloudiator/logs"
"$ROOT/scripts/install-retention-launchagent.sh"
"$ROOT/scripts/run-neon-retention.sh" || warn "retention run failed (check DATABASE_URL / Neon)"

section "Next (human)"
info "1) Playground: https://app.cloudiator.org/console — one chat, check Usage row"
info "2) Prove Netlify: curl -sI https://cloudiator.netlify.app/ | grep -i location  (expect 301 → app.)"
info "3) Salesforce Apex callout per docs/salesforce.md"
info "4) Merge Phase G PR #21 when ready, then Whisper weights + Android SIM bridge"
info "5) FileVault / auto-login / Slack alert — operator-checklist §6"

summary "Post-reboot finish line"
