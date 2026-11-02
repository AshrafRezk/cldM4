#!/usr/bin/env bash
# Nightly Neon usage retention (finish-line §3). Run from LaunchAgent, not pg_cron.
# Neon compute scales to zero; a Mini-side calendar job wakes it and deletes
# usage_events older than 30 days after rolling them into usage_daily.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/load-env.sh
. "$SCRIPT_DIR/lib/load-env.sh"

ENV_FILE="${CLOUDIATOR_ENV_FILE:-$HOME/Cloudiator/.env}"
load_env_file "$ENV_FILE"
# The worker keeps a 3s connect timeout so a request never waits on Neon. At
# 03:15 the compute is suspended and its cold start can take longer than that,
# which made every run since 2026-11-01 fail with TimeoutError. This job can wait.
export DB_CONNECT_TIMEOUT_SECONDS="${RETENTION_CONNECT_TIMEOUT_SECONDS:-30}"
RETENTION_ATTEMPTS="${RETENTION_ATTEMPTS:-3}"
export RETENTION_ATTEMPTS

SQL_PATH="${NEON_RETENTION_SQL:-$ROOT/infra/neon-retention.sql}"
WORKER="$ROOT/apps/worker"
PYTHON="$WORKER/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "missing $PYTHON — run scripts/mac-setup.sh first" >&2
  exit 1
fi
if [[ ! -f "$SQL_PATH" ]]; then
  echo "missing $SQL_PATH" >&2
  exit 1
fi

cd "$WORKER"
exec "$PYTHON" - "$SQL_PATH" <<'PY'
import asyncio
import os
import sys
from pathlib import Path

from app.config import get_settings
from app.db import DatabaseUnavailable, Neon

SQL_PATH = Path(sys.argv[1])

def statements(sql: str) -> list[str]:
    kept = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        kept.append(line)
    return [part.strip() for part in "\n".join(kept).split(";") if part.strip()]

async def main() -> None:
    db = Neon(get_settings())
    try:
        for stmt in statements(SQL_PATH.read_text()):
            await db.execute_script(stmt, timeout_seconds=120)

        async def counts(con):
            old = await con.fetchval(
                "SELECT count(*) FROM usage_events WHERE ts < now() - interval '30 days'"
            )
            total = await con.fetchval("SELECT count(*) FROM usage_events")
            days = await con.fetchval("SELECT count(*) FROM usage_daily")
            return old, total, days

        old, total, days = await db.run(counts, statement_timeout_seconds=30)
        print(
            f"retention ok: usage_events={total} older_than_30d={old} usage_daily_rows={days}",
            flush=True,
        )
    finally:
        await db.close()

async def with_retries() -> None:
    attempts = max(1, int(os.environ.get("RETENTION_ATTEMPTS", "3")))
    for attempt in range(1, attempts + 1):
        try:
            await main()
            return
        except DatabaseUnavailable as exc:
            if attempt == attempts:
                raise
            print(f"retention attempt {attempt} failed ({exc}); retrying", file=sys.stderr, flush=True)
            await asyncio.sleep(10 * attempt)

asyncio.run(with_retries())
PY
