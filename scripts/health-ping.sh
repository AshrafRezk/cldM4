#!/usr/bin/env bash
# Every-2-minute health ping (docs/host-setup.md §10, finish-line §6).
#
# Checks the worker on 127.0.0.1 and the same route through the tunnel, then
# alerts only when the overall state changes, so a long outage is one message
# and a recovery is another. Two consecutive failures are needed before "down",
# so a worker kickstart does not page anyone.
#
# Alert channels, from ~/Cloudiator/.env: SLACK_WEBHOOK_URL and/or NTFY_URL
# (e.g. https://ntfy.sh/<long-random-topic>, phone push with no account). With
# neither set it falls back to a macOS notification, which nobody sees on a
# headless Mini. Every alert is also a line in ~/Cloudiator/logs/health-ping.log.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/load-env.sh
. "$SCRIPT_DIR/lib/load-env.sh"

ENV_FILE="${CLOUDIATOR_ENV_FILE:-$HOME/Cloudiator/.env}"
[ -f "$ENV_FILE" ] && load_env_file "$ENV_FILE"

STATE_FILE="${HEALTH_PING_STATE:-$HOME/Cloudiator/health-ping.state}"
LOCAL_URL="${HEALTH_LOCAL_URL:-http://127.0.0.1:8080/v1/health}"
PUBLIC_URL="${PUBLIC_BASE_URL:-}"
PUBLIC_URL="${PUBLIC_URL%/}/v1/health"
PYTHON="$ROOT/apps/worker/.venv/bin/python"

# "ok" | "degraded: <reasons>" | "down: <why>"
probe() {
  local body
  if ! body="$(/usr/bin/curl -sf -m 10 "$LOCAL_URL")"; then
    echo "down: worker not answering on 127.0.0.1:8080"
    return
  fi
  local degraded
  degraded="$(printf '%s' "$body" | "$PYTHON" -c '
import json, sys
d = json.load(sys.stdin)
print("" if d.get("ok") else ",".join(d.get("degraded") or ["ok=false"]))
' 2>/dev/null)" || degraded="unparseable health body"
  if [ -n "${PUBLIC_BASE_URL:-}" ] && ! /usr/bin/curl -sf -m 20 -o /dev/null "$PUBLIC_URL"; then
    echo "down: $PUBLIC_URL unreachable (tunnel or Cloudflare)"
    return
  fi
  if [ -n "$degraded" ]; then
    echo "degraded: $degraded"
  else
    echo "ok"
  fi
}

alert() {
  local text="$1"
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$text"
  [ "${HEALTH_PING_DRY_RUN:-0}" = "1" ] && return 0
  if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
    local payload
    payload="$("$PYTHON" -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$text")"
    /usr/bin/curl -sS -m 15 -X POST -H 'Content-Type: application/json' \
      -d "$payload" "$SLACK_WEBHOOK_URL" >/dev/null || echo "slack post failed" >&2
  fi
  if [ -n "${NTFY_URL:-}" ]; then
    /usr/bin/curl -sS -m 15 -H "Title: Cloudiator" -d "$text" "$NTFY_URL" >/dev/null \
      || echo "ntfy post failed" >&2
  fi
  if [ -z "${SLACK_WEBHOOK_URL:-}" ] && [ -z "${NTFY_URL:-}" ]; then
    /usr/bin/osascript -e "display notification \"${text//\"/\'}\" with title \"Cloudiator\"" 2>/dev/null || true
  fi
}

current="$(probe)"
previous="ok"
fails=0
if [ -f "$STATE_FILE" ]; then
  previous="$(sed -n 1p "$STATE_FILE")"
  fails="$(sed -n 2p "$STATE_FILE")"
fi
[[ "$fails" =~ ^[0-9]+$ ]] || fails=0

if [ "$current" = "ok" ]; then
  fails=0
else
  fails=$((fails + 1))
fi

reported="$previous"
case "$current" in
  ok)
    [ "$previous" != "ok" ] && alert "Cloudiator Mini recovered: health ok" && reported="ok" ;;
  down:*)
    if [ "$fails" -ge 2 ] && [ "${previous%%:*}" != "down" ]; then
      alert "Cloudiator Mini DOWN — $current" && reported="$current"
    fi ;;
  degraded:*)
    if [ "$fails" -ge 2 ] && [ "$previous" != "$current" ]; then
      alert "Cloudiator Mini $current" && reported="$current"
    fi ;;
esac

printf '%s\n%s\n' "$reported" "$fails" > "$STATE_FILE"
