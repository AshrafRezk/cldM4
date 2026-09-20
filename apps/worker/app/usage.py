"""Usage accounting through a local SQLite outbox (PLAN.md §11).

A usage write must never block a response and never fail a request. So the
request path writes one row to `~/Cloudiator/queue.db` — local, single-digit
milliseconds, survives a restart — and a background task drains it to Neon every
10s in batches of 500.

The cap matters as much as the flush: an unbounded table on an appliance with no
operator fills the SSD, and a full SSD takes down Ollama, the worker, and
cloudflared at the same time. At 100k rows the oldest are dropped and the drop
is logged. Metrics are less important than the appliance staying up.

`outbox_depth` in /v1/health is the operator's signal: a depth that only grows
means Neon has been unreachable for a while.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from .db import DatabaseRejected, DatabaseUnavailable

log = logging.getLogger("cloudiator.usage")

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS usage_outbox (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  payload     TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0
);
"""

# One flush pass drains up to 10k rows so a backlog actually shrinks; a single
# 500-row batch every 10s would take hours to clear one.
MAX_BATCHES_PER_FLUSH = 20
DROP_LOG_INTERVAL_SECONDS = 60.0
# Routes that would drown the outbox without telling anyone anything.
SKIP_ROUTES = ("/v1/health",)


@dataclass
class UsageEvent:
    """One `usage_events` row (docs/schema.md)."""

    route: str
    status: int
    request_id: str | None = None
    key_id: str | None = None
    tenant_id: str | None = None
    model: str | None = None
    tool: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    bytes_out: int | None = None
    job_id: str | None = None
    error_code: str | None = None
    ts: str | None = None

    def payload(self) -> str:
        data = asdict(self)
        if not data.get("ts"):
            data["ts"] = datetime.now(timezone.utc).isoformat()
        return json.dumps(data, separators=(",", ":"))


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _row_from_payload(payload: str) -> Sequence[Any] | None:
    """Positional arguments for db.INSERT_USAGE_EVENT, or None if unusable."""
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    ts = data.get("ts")
    try:
        when = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
    except ValueError:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (
        _uuid_or_none(data.get("key_id")),
        _uuid_or_none(data.get("tenant_id")),
        when,
        data.get("request_id"),
        data.get("route") or "",
        data.get("model"),
        data.get("tool"),
        int(data.get("status") or 0),
        data.get("latency_ms"),
        data.get("prompt_tokens"),
        data.get("completion_tokens"),
        data.get("bytes_out"),
        _uuid_or_none(data.get("job_id")),
        data.get("error_code"),
    )


class UsageOutbox:
    def __init__(self, settings, db) -> None:
        self.settings = settings
        self.db = db
        self.path = settings.queue_db
        self.batch_size = settings.usage_flush_batch
        self.max_rows = settings.usage_outbox_max_rows
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._depth = 0
        self._dropped = 0
        self._last_drop_log = 0.0
        self._task: asyncio.Task | None = None
        self.flushed = 0

    # ---- lifecycle --------------------------------------------------------

    def open(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(
            self.path, timeout=1.0, isolation_level=None, check_same_thread=False
        )
        # WAL so the flusher reading a batch never blocks the request-path write.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(OUTBOX_DDL)
        self._conn = conn
        self._depth = int(conn.execute("SELECT count(*) FROM usage_outbox").fetchone()[0])
        log.info("usage outbox at %s (depth=%d)", self.path, self._depth)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                with suppress(Exception):
                    self._conn.close()
                self._conn = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._flush_loop(), name="usage-outbox-flush")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # ---- request path -----------------------------------------------------

    def depth(self) -> int:
        return self._depth

    def dropped(self) -> int:
        return self._dropped

    def record(self, event: UsageEvent) -> None:
        """Called from the request path. Swallows everything (PLAN.md §11).

        The insert runs inline rather than in a thread so a crash cannot lose a
        row that a response already reported. It can wait on the flusher's lock,
        but only for one WAL batch — milliseconds against a chat measured in tens
        of seconds.
        """
        if event.route in SKIP_ROUTES:
            return
        # An unauthenticated 401 flood would otherwise fill the outbox with rows
        # the dashboard cannot attribute to anyone. Cloudflare fronts that.
        if not event.key_id:
            return
        try:
            with self._lock:
                if self._conn is None:
                    return
                self._conn.execute(
                    "INSERT INTO usage_outbox (payload, created_at) VALUES (?, ?)",
                    (event.payload(), int(time.time())),
                )
                self._depth += 1
                if self._depth > self.max_rows:
                    self._drop_oldest_locked(self._depth - self.max_rows)
        except Exception as exc:  # noqa: BLE001 - usage must never fail a request
            log.warning("could not queue a usage row: %s", exc)

    def _drop_oldest_locked(self, count: int) -> None:
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM usage_outbox WHERE id IN "
            "(SELECT id FROM usage_outbox ORDER BY id LIMIT ?)",
            (count,),
        )
        removed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else count
        self._depth = max(0, self._depth - removed)
        self._dropped += removed
        now = time.monotonic()
        if now - self._last_drop_log >= DROP_LOG_INTERVAL_SECONDS:
            self._last_drop_log = now
            log.warning(
                "usage outbox is at its %d row cap; dropped %d oldest rows (%d total). "
                "Neon has probably been unreachable for a while",
                self.max_rows,
                removed,
                self._dropped,
            )

    # ---- flusher ----------------------------------------------------------

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.usage_flush_interval_seconds)
            try:
                await self.flush_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the flusher outlives its failures
                log.exception("usage flush pass failed")

    async def flush_once(self) -> int:
        """Drain the outbox to Neon. Returns the number of rows sent."""
        if self._conn is None or not self.db.configured:
            return 0
        sent = 0
        for _ in range(MAX_BATCHES_PER_FLUSH):
            batch = await asyncio.to_thread(self._take_batch)
            if not batch:
                break
            ids = [row_id for row_id, _ in batch]
            rows = [row for row in (_row_from_payload(payload) for _, payload in batch) if row]
            if rows:
                try:
                    await self.db.insert_usage_events(rows)
                except DatabaseUnavailable as exc:
                    await asyncio.to_thread(self._record_attempt, ids)
                    log.debug("usage flush deferred, Neon unreachable: %s", exc)
                    return sent
                except DatabaseRejected as exc:
                    log.warning("Neon refused a usage batch (%s); retrying row by row", exc)
                    if not await self._insert_individually(rows):
                        await asyncio.to_thread(self._record_attempt, ids)
                        return sent
            await asyncio.to_thread(self._delete, ids)
            sent += len(ids)
            self.flushed += len(ids)
            if len(batch) < self.batch_size:
                break
        return sent

    async def _insert_individually(self, rows: Sequence[Sequence[Any]]) -> bool:
        """Insert row by row so one refused row does not cost the whole batch.

        Returns False when Neon became unreachable mid-way, so the caller leaves
        the batch queued instead of deleting rows that never landed.
        """
        refused = 0
        for row in rows:
            try:
                await self.db.insert_usage_event(row)
            except DatabaseRejected:
                refused += 1
            except DatabaseUnavailable:
                return False
        if refused:
            self._dropped += refused
            log.warning("dropped %d usage rows Neon refused individually", refused)
        return True

    def _take_batch(self) -> list[tuple[int, str]]:
        with self._lock:
            if self._conn is None:
                return []
            return [
                (int(row[0]), row[1])
                for row in self._conn.execute(
                    "SELECT id, payload FROM usage_outbox ORDER BY id LIMIT ?",
                    (self.batch_size,),
                ).fetchall()
            ]

    def _delete(self, ids: Sequence[int]) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._conn.executemany("DELETE FROM usage_outbox WHERE id = ?", [(i,) for i in ids])
            self._depth = max(0, self._depth - len(ids))

    def _record_attempt(self, ids: Sequence[int]) -> None:
        """Count a deferred flush. Rows stay queued; the 100k cap is the bound.

        Deliberately not a give-up counter: during a long Neon outage every row
        is retried, and dropping perfectly good rows after five attempts would
        lose a morning of usage for an appliance that was working fine.
        """
        with self._lock:
            if self._conn is None:
                return
            self._conn.executemany(
                "UPDATE usage_outbox SET attempts = attempts + 1 WHERE id = ?",
                [(i,) for i in ids],
            )
