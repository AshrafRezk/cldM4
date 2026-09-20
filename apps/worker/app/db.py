"""Neon Postgres client (PLAN.md §11).

Neon is never on the critical path of a chat response. Auth falls back to the
60s key cache and usage falls back to the SQLite outbox, so everything here is
allowed to fail: callers catch `DatabaseUnavailable` and carry on.

Three properties this module exists to hold:

1. The pool is **0 min / 2 max**. One appliance, one process. A Neon compute
   auto-suspends after about five idle minutes, so extra connections buy
   nothing and cost quota.
2. Every connection is **pre-pinged** and recycled after 300s. A socket that
   survived an idle suspend looks alive until the first query fails, and that
   query would otherwise be an auth lookup.
3. A dead Neon must not add latency. After a few consecutive failures the
   breaker opens and calls fail immediately instead of spending the connect
   timeout, which is what keeps a Neon outage off the request path.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, Awaitable, Callable, Sequence

import asyncpg

log = logging.getLogger("cloudiator.db")

STATE_NOT_CONFIGURED = "not_configured"
STATE_UNKNOWN = "unknown"
STATE_OK = "ok"
STATE_DEGRADED = "degraded"

BREAKER_FAILURES = 3
BREAKER_COOLDOWN_SECONDS = 15.0
PING_TIMEOUT_SECONDS = 2.0
SCHEMA_TIMEOUT_SECONDS = 10.0
# The 5s statement timeout protects a request budget. The outbox flusher is a
# background task writing 500 rows at a time, so it gets its own.
FLUSH_TIMEOUT_SECONDS = 15.0

# asyncpg turns unrecognised DSN query parameters into server settings, which
# Postgres then rejects as unknown GUCs. Neon hands out connection strings with
# extras like `channel_binding=require`, so only the ones asyncpg understands
# survive.
DSN_QUERY_ALLOWLIST = (
    "sslmode",
    "sslcert",
    "sslkey",
    "sslrootcert",
    "target_session_attrs",
)

# Looked up by the indexed public_id, and revoked keys are simply not there:
# a revoked key must be indistinguishable from one that never existed.
SELECT_API_KEY_BY_PUBLIC_ID = """
SELECT id, tenant_id, public_id, secret_hash, name, preset, capabilities, models,
       tools, max_tokens, max_context, rpm, daily_token_budget, allowed_origins,
       salesforce_org_id, log_prompts, strip_exif, force_no_stream,
       max_response_bytes, revoked_at
FROM api_keys
WHERE public_id = $1 AND revoked_at IS NULL
"""

INSERT_USAGE_EVENT = """
INSERT INTO usage_events (
  key_id, tenant_id, ts, request_id, route, model, tool, status, latency_ms,
  prompt_tokens, completion_tokens, bytes_out, job_id, error_code
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
"""

EXPECTED_TABLES = ("tenants", "api_keys", "usage_events", "usage_daily", "jobs")


class DatabaseUnavailable(RuntimeError):
    """Neon could not answer. Fall back to the key cache or the outbox."""


class DatabaseRejected(RuntimeError):
    """Neon answered and refused the statement.

    Separate from `DatabaseUnavailable` because the two need opposite handling:
    an unreachable Neon means retry later, a refused row means retrying forever
    would wedge the outbox behind it.
    """


def normalize_dsn(url: str) -> str:
    """Drop query parameters asyncpg would forward to Postgres as GUCs."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    kept = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if name in DSN_QUERY_ALLOWLIST
    ]
    dropped = {
        name for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    } - {name for name, _ in kept}
    if dropped:
        log.debug("ignoring DSN parameters asyncpg cannot use: %s", sorted(dropped))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(kept)))


def pooled_endpoint(url: str | None) -> bool:
    """True for the `-pooler` host Neon expects a long-lived process to use."""
    if not url:
        return False
    host = urllib.parse.urlsplit(url).hostname or ""
    return "-pooler." in host


class Neon:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()
        self._failures = 0
        self._breaker_open_until = 0.0
        self._state = STATE_NOT_CONFIGURED if not settings.database_url else STATE_UNKNOWN
        self._last_error: str | None = None

    # ---- state ------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.settings.database_url)

    def state(self) -> str:
        """Last known state. /v1/health must never round-trip Neon (PLAN.md §10)."""
        return self._state

    def last_error(self) -> str | None:
        return self._last_error

    def _record_success(self) -> None:
        self._failures = 0
        self._breaker_open_until = 0.0
        self._last_error = None
        if self._state != STATE_OK:
            log.info("neon reachable again")
        self._state = STATE_OK

    def _record_failure(self, exc: BaseException) -> None:
        self._failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        if self._state != STATE_DEGRADED:
            log.warning("neon is degraded: %s", self._last_error)
        self._state = STATE_DEGRADED
        if self._failures >= BREAKER_FAILURES:
            self._breaker_open_until = (
                asyncio.get_running_loop().time() + BREAKER_COOLDOWN_SECONDS
            )

    def _breaker_is_open(self) -> bool:
        if not self._breaker_open_until:
            return False
        if asyncio.get_running_loop().time() >= self._breaker_open_until:
            # One request is allowed through to find out whether Neon is back.
            self._breaker_open_until = 0.0
            self._failures = BREAKER_FAILURES - 1
            return False
        return True

    # ---- plumbing ---------------------------------------------------------

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        if not self.configured:
            raise DatabaseUnavailable("DATABASE_URL is not set")
        async with self._pool_lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    normalize_dsn(self.settings.database_url),
                    min_size=self.settings.db_pool_min,
                    max_size=self.settings.db_pool_max,
                    max_inactive_connection_lifetime=self.settings.db_pool_recycle_seconds,
                    command_timeout=self.settings.db_statement_timeout_seconds,
                    timeout=self.settings.db_connect_timeout_seconds,
                    # The pooled Neon endpoint is PgBouncer in transaction mode;
                    # asyncpg's implicit prepared statements break there.
                    statement_cache_size=0,
                    server_settings={"application_name": "cloudiator-worker"},
                )
                log.info(
                    "neon pool ready (min=%s max=%s recycle=%ss pooled_endpoint=%s)",
                    self.settings.db_pool_min,
                    self.settings.db_pool_max,
                    self.settings.db_pool_recycle_seconds,
                    pooled_endpoint(self.settings.database_url),
                )
        return self._pool

    @asynccontextmanager
    async def _connection(self):
        """Acquire a pre-pinged connection, replacing one dead socket."""
        pool = await self._ensure_pool()
        last: BaseException | None = None
        for _ in range(2):
            con = await pool.acquire(timeout=self.settings.db_connect_timeout_seconds)
            try:
                await con.fetchval("SELECT 1", timeout=PING_TIMEOUT_SECONDS)
            except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
                last = exc
                with suppress(Exception):
                    con.terminate()
                await pool.release(con)
                continue
            try:
                yield con
            finally:
                await pool.release(con)
            return
        raise DatabaseUnavailable(f"no usable Neon connection: {last}")

    async def run(
        self,
        action: Callable[[Any], Awaitable[Any]],
        *,
        statement_timeout_seconds: float | None = None,
    ) -> Any:
        """Run `action` in a transaction with a server-side statement timeout.

        `SET LOCAL` is the form that survives PgBouncer transaction pooling: the
        server connection is ours for the length of the transaction and the
        setting is dropped at commit.
        """
        if not self.configured:
            raise DatabaseUnavailable("DATABASE_URL is not set")
        if self._breaker_is_open():
            raise DatabaseUnavailable(f"neon breaker is open ({self._last_error})")

        timeout = statement_timeout_seconds or self.settings.db_statement_timeout_seconds
        try:
            async with self._connection() as con:
                async with con.transaction():
                    await con.execute(f"SET LOCAL statement_timeout = {int(timeout * 1000)}")
                    result = await action(con)
        except DatabaseUnavailable as exc:
            self._record_failure(exc)
            raise
        except (asyncpg.DataError, asyncpg.IntegrityConstraintViolationError) as exc:
            # The connection is fine; this statement is not. Neon is not degraded.
            self._record_success()
            raise DatabaseRejected(f"{type(exc).__name__}: {exc}") from exc
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError) as exc:
            self._record_failure(exc)
            raise DatabaseUnavailable(f"{type(exc).__name__}: {exc}") from exc
        self._record_success()
        return result

    async def close(self) -> None:
        if self._pool is not None:
            pool, self._pool = self._pool, None
            with suppress(Exception):
                await pool.close()

    # ---- queries ----------------------------------------------------------

    async def fetch_api_key(self, public_id: str) -> dict[str, Any] | None:
        """Look up by the indexed public_id. The secret is verified in auth.py."""

        async def action(con):
            return await con.fetchrow(SELECT_API_KEY_BY_PUBLIC_ID, public_id)

        row = await self.run(action)
        return dict(row) if row is not None else None

    async def insert_usage_events(self, rows: Sequence[Sequence[Any]]) -> None:
        """Batch insert from the outbox flusher. Never called from a request."""

        async def action(con):
            await con.executemany(INSERT_USAGE_EVENT, rows, timeout=FLUSH_TIMEOUT_SECONDS)

        await self.run(action, statement_timeout_seconds=FLUSH_TIMEOUT_SECONDS)

    async def insert_usage_event(self, row: Sequence[Any]) -> None:
        """One row, so a batch Neon refused can be retried without its poison."""

        async def action(con):
            await con.execute(INSERT_USAGE_EVENT, *row, timeout=FLUSH_TIMEOUT_SECONDS)

        await self.run(action, statement_timeout_seconds=FLUSH_TIMEOUT_SECONDS)

    async def fetch_usage_rollup(self, key_id: str, days: int) -> dict[str, Any]:
        async def action(con):
            return await con.fetchrow(
                """
                SELECT coalesce(sum(calls), 0)             AS calls,
                       coalesce(sum(errors), 0)            AS errors,
                       coalesce(sum(prompt_tokens), 0)     AS prompt_tokens,
                       coalesce(sum(completion_tokens), 0) AS completion_tokens,
                       coalesce(sum(bytes_out), 0)         AS bytes_out
                FROM usage_daily
                WHERE key_id = $1 AND day >= (current_date - $2::int)
                """,
                key_id,
                days,
            )

        row = await self.run(action)
        return {key: int(value) for key, value in dict(row or {}).items()}

    async def fetch_usage_events(self, key_id: str, limit: int) -> list[dict[str, Any]]:
        async def action(con):
            return await con.fetch(
                """
                SELECT ts, request_id, route, model, tool, status, latency_ms,
                       prompt_tokens, completion_tokens, bytes_out, error_code
                FROM usage_events
                WHERE key_id = $1
                ORDER BY ts DESC
                LIMIT $2
                """,
                key_id,
                limit,
            )

        rows = await self.run(action)
        events: list[dict[str, Any]] = []
        for row in rows:
            event = dict(row)
            ts = event.get("ts")
            if isinstance(ts, datetime):
                event["ts"] = ts.isoformat()
            events.append(event)
        return events

    async def ping(self) -> float:
        """Round-trip time in ms. Only /v1/health/deep and the CLI use this."""
        loop = asyncio.get_running_loop()

        async def action(con):
            await con.fetchval("SELECT 1", timeout=PING_TIMEOUT_SECONDS)

        started = loop.time()
        await self.run(action, statement_timeout_seconds=PING_TIMEOUT_SECONDS)
        return (loop.time() - started) * 1000.0

    async def missing_tables(self) -> list[str]:
        """Which of the documented tables are absent (docs/schema.md)."""

        async def action(con):
            return await con.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ANY($1::text[])",
                list(EXPECTED_TABLES),
                timeout=SCHEMA_TIMEOUT_SECONDS,
            )

        rows = await self.run(action, statement_timeout_seconds=SCHEMA_TIMEOUT_SECONDS)
        present = {row["table_name"] for row in rows}
        return [name for name in EXPECTED_TABLES if name not in present]

    async def execute_script(self, sql: str, *, timeout_seconds: float = 60.0) -> None:
        """Apply infra/neon.sql. Every statement in it is IF NOT EXISTS."""

        async def action(con):
            # A cold Neon compute plus DDL is slower than the 5s request budget,
            # and this path is a human at a terminal, not a caller.
            await con.execute(sql, timeout=timeout_seconds)

        await self.run(action, statement_timeout_seconds=timeout_seconds)
