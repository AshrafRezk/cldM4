#!/usr/bin/env bash
# Named Cloudflare Tunnel to 127.0.0.1:8080 only — Phase B step 7.
#
#   scripts/install-tunnel.sh                       # api.cloudiator.org, quic
#   TUNNEL_HOSTNAME=api.example.com scripts/install-tunnel.sh
#   TUNNEL_PROTOCOL=http2 scripts/install-tunnel.sh # Wi-Fi only, or broken QUIC UDP
#   scripts/install-tunnel.sh --uninstall
#
# Prerequisites, both done by a human first (docs/host-setup.md §8):
#   cloudflared tunnel login      # browser, picks the zone
#   the Cloudflare zone must show Active
#
# This script creates the named tunnel if it does not exist, renders
# ~/.cloudflared/config.yml from infra/cloudflared/config.yml, routes the DNS
# record, and bootstraps the LaunchAgent. It refuses to write an ingress that
# mentions 11434 or any port other than 8080.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TUNNEL_NAME="${TUNNEL_NAME:-cloudiator-mini}"
TUNNEL_HOSTNAME="${TUNNEL_HOSTNAME:-api.cloudiator.org}"
TUNNEL_PROTOCOL="${TUNNEL_PROTOCOL:-quic}"
LABEL="com.cloudiator.cloudflared"
CONFIG="$HOME/.cloudflared/config.yml"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

require_arm64_macos

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && pass "booted out $LABEL" || info "$LABEL was not loaded"
  rm -f "$PLIST_DEST" && pass "removed $PLIST_DEST"
  info "the tunnel itself and its DNS record survive. To remove them too:"
  info "  cloudflared tunnel delete $TUNNEL_NAME    # then delete the CNAME in Cloudflare DNS"
  summary "Tunnel uninstall"
  exit $?
fi

printf '%sPhase B tunnel%s  (%s -> http://127.0.0.1:8080)\n' "$C_BOLD" "$C_OFF" "$TUNNEL_HOSTNAME"

# --------------------------------------------------------------------------
section "Preflight"

CLOUDFLARED="$(command -v cloudflared 2>/dev/null)"
[ -n "$CLOUDFLARED" ] || die "cloudflared is not installed: brew install cloudflared"
pass "cloudflared at $CLOUDFLARED"

[ -f "$HOME/.cloudflared/cert.pem" ] \
  && pass "cloudflared is logged in" \
  || die "run 'cloudflared tunnel login' first (it needs a browser and the zone must be Active)"

if curl -fsS --max-time 3 http://127.0.0.1:8080/v1/health >/dev/null 2>&1; then
  pass "the worker answers on 127.0.0.1:8080"
else
  warn "the worker is not answering on 127.0.0.1:8080 — the tunnel will 502 until it does"
fi

case "$TUNNEL_PROTOCOL" in
  quic)  info "protocol quic. If the tunnel flaps, re-run with TUNNEL_PROTOCOL=http2" ;;
  http2) pass "protocol http2 (Wi-Fi-only installs and ISPs that break QUIC UDP)" ;;
  *)     die "TUNNEL_PROTOCOL must be quic or http2, got '$TUNNEL_PROTOCOL'" ;;
esac

# --------------------------------------------------------------------------
section "Named tunnel"

UUID="$("$CLOUDFLARED" tunnel list --output json 2>/dev/null \
  | "$ROOT/apps/worker/.venv/bin/python" -c '
import json, sys
name = sys.argv[1]
try:
    tunnels = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for tunnel in tunnels:
    if tunnel.get("name") == name and not tunnel.get("deleted_at"):
        print(tunnel.get("id", ""))
        break
' "$TUNNEL_NAME")"

if [ -z "$UUID" ]; then
  info "creating tunnel $TUNNEL_NAME"
  "$CLOUDFLARED" tunnel create "$TUNNEL_NAME" || die "could not create the tunnel"
  UUID="$("$CLOUDFLARED" tunnel list --output json 2>/dev/null \
    | "$ROOT/apps/worker/.venv/bin/python" -c '
import json, sys
for tunnel in json.load(sys.stdin):
    if tunnel.get("name") == sys.argv[1] and not tunnel.get("deleted_at"):
        print(tunnel.get("id", ""))
        break
' "$TUNNEL_NAME")"
fi

[ -n "$UUID" ] || die "could not determine the tunnel UUID"
pass "tunnel $TUNNEL_NAME is $UUID"

CREDENTIALS="$HOME/.cloudflared/$UUID.json"
[ -f "$CREDENTIALS" ] \
  && pass "credentials file present" \
  || die "no $CREDENTIALS. Re-run 'cloudflared tunnel create $TUNNEL_NAME' on this Mini."
chmod 600 "$CREDENTIALS" 2>/dev/null

# --------------------------------------------------------------------------
section "Render ~/.cloudflared/config.yml"

mkdir -p "$HOME/.cloudflared" "$HOME/Cloudiator/logs" "$HOME/Library/LaunchAgents"

if [ -f "$CONFIG" ]; then
  cp "$CONFIG" "$CONFIG.bak" && info "kept the previous config at $CONFIG.bak"
fi

sed -e "s|__TUNNEL_UUID__|$UUID|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__HOSTNAME__|$TUNNEL_HOSTNAME|g" \
    -e "s|__PROTOCOL__|$TUNNEL_PROTOCOL|g" \
    "$ROOT/infra/cloudflared/config.yml" > "$CONFIG" || die "could not write $CONFIG"

if grep -q '__[A-Z_]*__' "$CONFIG"; then
  rm -f "$CONFIG"
  die "a placeholder survived substitution; refusing to install a config that cannot run"
fi
pass "wrote $CONFIG"

# The one thing that must never be wrong.
if [ "$(grep -c 11434 "$CONFIG")" != "0" ]; then
  rm -f "$CONFIG"
  die "11434 appears in the ingress. That would put Ollama on the public internet with no auth."
fi
pass "11434 does not appear in the ingress"

PORT_LINES="$(grep -c 'service: http://' "$CONFIG")"
if [ "$PORT_LINES" != "1" ]; then
  die "$PORT_LINES http services in the ingress, expected exactly 1 (and it must be 8080)"
fi
grep -q 'service: http://127.0.0.1:8080' "$CONFIG" \
  && pass "the only origin is http://127.0.0.1:8080" \
  || die "the origin is not http://127.0.0.1:8080"
grep -q '^no-autoupdate: true' "$CONFIG" \
  && pass "no-autoupdate: true (a self-update would restart the tunnel mid-job)" \
  || fail "no-autoupdate is not true"

# --------------------------------------------------------------------------
section "DNS"

if "$CLOUDFLARED" tunnel route dns "$TUNNEL_NAME" "$TUNNEL_HOSTNAME" 2>/tmp/cloudiator-route.log; then
  pass "$TUNNEL_HOSTNAME CNAME -> $UUID.cfargotunnel.com"
else
  if grep -qi 'already exists\|record with that host' /tmp/cloudiator-route.log; then
    pass "$TUNNEL_HOSTNAME already routes to this tunnel"
  else
    fail "could not route DNS: $(head -2 /tmp/cloudiator-route.log | tr '\n' ' ')"
    info "create the CNAME by hand: $TUNNEL_HOSTNAME -> $UUID.cfargotunnel.com, proxied"
  fi
fi
rm -f /tmp/cloudiator-route.log

# --------------------------------------------------------------------------
section "LaunchAgent"

# On Sequoia a process first launched by launchd can be denied Local Network
# access with no visible prompt, and the tunnel then behaves exactly as if the
# worker is down (docs/host-setup.md §4).
info "if you have never run cloudflared interactively on this Mini, do that once first:"
info "  cloudflared tunnel run $TUNNEL_NAME    # approve the Local Network prompt, then Ctrl-C"

sed -e "s|__HOME__|$HOME|g" -e "s|__CLOUDFLARED__|$CLOUDFLARED|g" \
    "$ROOT/infra/launchd/$LABEL.plist" > "$PLIST_DEST" || die "could not write $PLIST_DEST"
if grep -q '__[A-Z_]*__\|/Users/REPLACE' "$PLIST_DEST"; then
  rm -f "$PLIST_DEST"
  die "placeholder survived substitution in $PLIST_DEST"
fi
pass "wrote $PLIST_DEST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && info "booted out the previous instance"
sleep 1
launchctl bootstrap "gui/$UID" "$PLIST_DEST" 2>/dev/null \
  && pass "bootstrapped $LABEL" \
  || fail "launchctl bootstrap failed (check $HOME/Cloudiator/logs/cloudflared.err)"
launchctl enable "gui/$UID/$LABEL" 2>/dev/null && pass "enabled $LABEL"
launchctl kickstart -k "gui/$UID/$LABEL" 2>/dev/null && pass "kickstarted $LABEL"

READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if pgrep -f "cloudflared.*tunnel.*run" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
[ "$READY" = "1" ] && pass "cloudflared is running" || fail "cloudflared did not stay up"

section "Next"
info "prove it from a phone on cellular, not this Mini's network:"
info "  scripts/smoke-phase-b.sh"
info "zone settings that Salesforce needs (Bot Fight Mode OFF, WAF skip rule): operator-checklist §2a-2b"

summary "Tunnel install"
