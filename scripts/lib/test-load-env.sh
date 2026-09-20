#!/usr/bin/env bash
# Proof that load-env.sh accepts the documented Nominatim User-Agent without
# evaluating the file as shell. Run from anywhere:
#
#   scripts/lib/test-load-env.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=load-env.sh
. "$DIR/load-env.sh"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<'EOF'
# a comment

DATABASE_URL=postgresql://u:p@ep-x-pooler.example/neondb?sslmode=require
export ADMIN_TOKEN=exported-token
CF_ACCESS_AUD="quoted-aud"
NOMINATIM_USER_AGENT=Cloudiator/0.1 (someone@example.com)
AFTER_UA=still-loaded
EVIL=$(echo pwned)
not-a-variable-line
EOF

# The point of this loader: unquoted parentheses must not abort, and later
# lines must still be read. `source` in zsh stops at the User-Agent line.
load_env_file "$TMP"

fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

[ "${NOMINATIM_USER_AGENT}" = "Cloudiator/0.1 (someone@example.com)" ] \
  || fail "User-Agent was ${NOMINATIM_USER_AGENT-unset}"
[ "${ADMIN_TOKEN}" = "exported-token" ] || fail "export prefix"
[ "${CF_ACCESS_AUD}" = "quoted-aud" ] || fail "quoted value"
[ "${DATABASE_URL}" = "postgresql://u:p@ep-x-pooler.example/neondb?sslmode=require" ] \
  || fail "value containing ="
[ "${AFTER_UA}" = "still-loaded" ] || fail "line after the User-Agent was skipped"
[ "${EVIL}" = '$(echo pwned)' ] || fail "command substitution was evaluated"

# Missing file is a no-op, not an abort (setup scripts run before the file exists).
load_env_file "$TMP.missing"

printf 'PASS load-env.sh\n'
