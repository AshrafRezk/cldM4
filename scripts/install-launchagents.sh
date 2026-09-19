#!/usr/bin/env bash
# Render and bootstrap the worker LaunchAgent (docs/host-setup.md §6).
#
#   scripts/install-launchagents.sh
#   scripts/install-launchagents.sh --uninstall
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LABEL="ai.cloudiator.worker"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
WRAPPER_DEST="$HOME/Cloudiator/run-worker.sh"

require_arm64_macos

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && pass "booted out $LABEL" || info "$LABEL was not loaded"
  rm -f "$PLIST_DEST" && pass "removed $PLIST_DEST"
  summary "Uninstall"
  exit $?
fi

section "Preflight"

[ -x "$ROOT/apps/worker/.venv/bin/uvicorn" ] \
  && pass "worker venv is built" \
  || die "no $ROOT/apps/worker/.venv/bin/uvicorn. Run scripts/mac-setup.sh first."

if [ -f "$HOME/Cloudiator/.env" ]; then
  pass "~/Cloudiator/.env exists"
  grep -q '^OLLAMA_MAX_LOADED_MODELS=2$' "$HOME/Cloudiator/.env" \
    && pass "OLLAMA_MAX_LOADED_MODELS=2 is in .env" \
    || warn "add OLLAMA_MAX_LOADED_MODELS=2 to ~/Cloudiator/.env or the worker refuses to boot"
else
  die "no ~/Cloudiator/.env. cp .env.example ~/Cloudiator/.env && chmod 600 ~/Cloudiator/.env"
fi

mkdir -p "$HOME/Cloudiator/logs" "$HOME/Library/LaunchAgents"

# On Sequoia a process first launched by launchd can be denied Local Network
# access with no visible prompt, and the worker then behaves exactly as if
# Ollama is down (docs/host-setup.md §4).
info "if you have never run the worker interactively on this machine, do that once first:"
info "  cd apps/worker && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1"

section "Render templates"

render() {
  sed -e "s|__HOME__|$HOME|g" -e "s|__REPO__|$ROOT|g" "$1" > "$2" || die "could not write $2"
  if grep -q '__HOME__\|__REPO__\|/Users/REPLACE' "$2"; then
    rm -f "$2"
    die "placeholder survived substitution in $2 — refusing to install a plist that cannot exec"
  fi
  pass "wrote $2"
}

render "$ROOT/infra/launchd/run-worker.sh" "$WRAPPER_DEST"
chmod +x "$WRAPPER_DEST" && pass "chmod +x $WRAPPER_DEST"
render "$ROOT/infra/launchd/$LABEL.plist" "$PLIST_DEST"

section "Bootstrap (launchctl bootstrap, not the deprecated load)"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && info "booted out the previous instance"
sleep 1
launchctl bootstrap "gui/$UID" "$PLIST_DEST" 2>/dev/null \
  && pass "bootstrapped $LABEL" \
  || fail "launchctl bootstrap failed (check $HOME/Cloudiator/logs/worker.err)"
launchctl enable "gui/$UID/$LABEL" 2>/dev/null && pass "enabled $LABEL"
launchctl kickstart -k "gui/$UID/$LABEL" 2>/dev/null && pass "kickstarted $LABEL"

section "Verify it is serving, not just running"

READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/v1/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" = "1" ]; then
  pass "/v1/health answers on 127.0.0.1:8080"
else
  fail "no answer from /v1/health after 15s"
  info "the boot gates refuse to start on a bad configuration; read the reason:"
  info "  tail -40 $HOME/Cloudiator/logs/worker.err"
fi

launchctl print "gui/$UID/$LABEL" 2>/dev/null | head -20

section "Next"
info "scripts/smoke-phase-a.sh"

summary "LaunchAgent install"
