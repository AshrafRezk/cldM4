#!/usr/bin/env bash
# Install a 2-minute local health ping that posts to Slack when /v1/health fails.
# Requires SLACK_WEBHOOK_URL in ~/Cloudiator/.env (never commit that file).
set -euo pipefail

ENV_FILE="${CLOUDIATOR_ENV:-$HOME/Cloudiator/.env}"
LOG_DIR="${CLOUDIATOR_LOG_DIR:-$HOME/Cloudiator/logs}"
PLIST_DIR="$HOME/Library/LaunchAgents"
LABEL="ai.cloudiator.health-alert"
PLIST="$PLIST_DIR/$LABEL.plist"
RUNNER="$HOME/Cloudiator/bin/cloudiator-health-alert.sh"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
# Only pull the webhook; do not source the whole .env into this shell's export of secrets to children beyond the runner.
WEBHOOK="$(/usr/bin/awk -F= '/^SLACK_WEBHOOK_URL=/{sub(/^SLACK_WEBHOOK_URL=/,""); print; exit}' "$ENV_FILE" | tr -d '"' | tr -d "'")"
set +a

if [[ -z "${WEBHOOK:-}" ]]; then
  echo "SLACK_WEBHOOK_URL is empty in $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$RUNNER")" "$PLIST_DIR"

cat > "$RUNNER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ENV_FILE="${CLOUDIATOR_ENV:-$HOME/Cloudiator/.env}"
WEBHOOK="$(/usr/bin/awk -F= '/^SLACK_WEBHOOK_URL=/{sub(/^SLACK_WEBHOOK_URL=/,""); print; exit}' "$ENV_FILE" | tr -d '"' | tr -d "'")"
if /usr/bin/curl -sf --max-time 5 http://127.0.0.1:8080/v1/health >/dev/null; then
  exit 0
fi
if [[ -z "${WEBHOOK:-}" ]]; then
  echo "health failed and SLACK_WEBHOOK_URL empty" >&2
  exit 1
fi
/usr/bin/curl -sS --max-time 10 -X POST "$WEBHOOK" \
  -H 'Content-Type: application/json' \
  -d "{\"text\":\"Cloudiator Mini health failed ($(hostname -s) $(date -u +%Y-%m-%dT%H:%M:%SZ))\"}" >/dev/null
EOF
chmod 700 "$RUNNER"

UID_NUM="$(id -u)"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER</string>
  </array>
  <key>StartInterval</key>
  <integer>120</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/health-alert.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/health-alert.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/$LABEL" 2>/dev/null || true

echo "installed $PLIST"
echo "runner  $RUNNER"
echo "prove:  launchctl print gui/$UID_NUM/$LABEL | head -20"
echo "drill:  launchctl bootout gui/$UID_NUM/ai.cloudiator.worker"
echo "        wait ≤2 min for Slack, then:"
echo "        launchctl bootstrap gui/$UID_NUM ~/Library/LaunchAgents/ai.cloudiator.worker.plist"
echo "repo ref: $REPO_ROOT/docs/host-setup.md §10"
