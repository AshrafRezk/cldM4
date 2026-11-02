#!/usr/bin/env bash
# Restart the worker without the ~90 s gap `launchctl kickstart -k` causes.
#
# kickstart -k starts the new process while the old one is still shutting
# down; the single-worker boot gate refuses it, and launchd's respawn throttle
# then holds the next try. Stopping first and waiting for the old pid to exit
# keeps the gap to the boot time (a few seconds).
set -euo pipefail

LABEL="ai.cloudiator.worker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HEALTH="http://127.0.0.1:8080/v1/health"

[ -f "$PLIST" ] || { echo "missing $PLIST (run scripts/install-launchagents.sh)" >&2; exit 1; }

old_pids="$(pgrep -f 'uvicorn app.main:app' || true)"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
for _ in $(seq 1 60); do
  alive=""
  for pid in $old_pids; do kill -0 "$pid" 2>/dev/null && alive=1; done
  [ -z "$alive" ] && break
  sleep 0.5
done
[ -n "${alive:-}" ] && { echo "old worker ($old_pids) did not exit in 30 s" >&2; exit 1; }

started=$(date +%s)
launchctl bootstrap "gui/$UID" "$PLIST"
for _ in $(seq 1 120); do
  if body="$(/usr/bin/curl -sf -m 3 "$HEALTH")"; then
    echo "worker up in $(( $(date +%s) - started ))s: $body"
    exit 0
  fi
  sleep 0.5
done
echo "worker did not answer $HEALTH within 60 s; see ~/Cloudiator/logs/worker.err" >&2
exit 1
