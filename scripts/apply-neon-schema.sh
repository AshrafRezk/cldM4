#!/usr/bin/env bash
# Verify (and only if needed, apply) the Neon schema — Phase B step 1.
#
#   scripts/apply-neon-schema.sh            # verify, apply only what is missing
#   scripts/apply-neon-schema.sh --verify   # report and change nothing
#
# infra/neon.sql is a copy of docs/schema.md and every statement in it is
# IF NOT EXISTS, so this is safe to run against a project that already has the
# tables. It reads DATABASE_URL from ~/Cloudiator/.env and never prints it.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKER="$ROOT/apps/worker"
VENV_PY="$WORKER/.venv/bin/python"

load_env_file "$HOME/Cloudiator/.env"

section "Preflight"

[ -x "$VENV_PY" ] || die "no venv at $VENV_PY. Run scripts/mac-setup.sh first."
pass "worker venv is built"

if [ -z "${DATABASE_URL:-}" ]; then
  die "DATABASE_URL is not in ~/Cloudiator/.env. Paste the POOLED Neon URL there (chmod 600)."
fi
pass "DATABASE_URL is set"

# The Mini holds one process for weeks against a compute that auto-suspends;
# a direct endpoint loses its connection on every suspend (PLAN.md §11).
case "$DATABASE_URL" in
  *-pooler.*) pass "DATABASE_URL is the pooled endpoint" ;;
  *)          fail "DATABASE_URL has no '-pooler' in the host. Use the pooled Neon endpoint" ;;
esac

if [ -f "$HOME/Cloudiator/.env" ]; then
  PERMS="$(file_mode "$HOME/Cloudiator/.env")"
  [ "$PERMS" = "600" ] && pass ".env is chmod 600" || fail ".env is $PERMS, expected 600: chmod 600 ~/Cloudiator/.env"
fi

section "Schema"

if (cd "$WORKER" && "$VENV_PY" -m app.dbtool verify-schema); then
  pass "every documented table is present"
  summary "Neon schema"
  exit $?
fi

if [ "${1:-}" = "--verify" ]; then
  fail "tables are missing; re-run without --verify to apply infra/neon.sql"
  summary "Neon schema"
  exit 1
fi

info "applying $ROOT/infra/neon.sql (idempotent: every statement is IF NOT EXISTS)"
if (cd "$WORKER" && "$VENV_PY" -m app.dbtool apply-schema --file "$ROOT/infra/neon.sql"); then
  pass "schema applied"
else
  fail "could not apply the schema; the output above says why"
fi

section "Next"
info "mint a key:   cd apps/worker && .venv/bin/python -m app.dbtool mint-key --tenant cloudiator --name 'Salesforce dev' --preset salesforce_engineer"
info "then:         scripts/install-tunnel.sh && scripts/smoke-phase-b.sh"
info "retention:    schedule infra/neon-retention.sql (operator-checklist §3)"

summary "Neon schema"
