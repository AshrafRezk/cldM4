"""SQLite job queue (PLAN.md §10).

Lives in QUEUE_DB next to the usage outbox so a restart does not drop a FLUX
run. Idempotency-Key is unique per key for 24h and a repeat returns the
original row. Images are always a job: a 1024² generate takes about two
minutes, past the 90s sync deadline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.jobs")

IDEMPOTENCY_SECONDS = 24 * 60 * 60
POLL_SECONDS = 0.5

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    key_id TEXT NOT NULL,
    tenant_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    idempotency_key TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency
    ON jobs(key_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""


class JobStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_DDL)
        now = time.time()
        conn.execute(
            "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
            (now,),
        )
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def enqueue(
        self,
        *,
        key_id: str,
        tenant_id: str | None,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Return (job, created). created is false when the idempotency key hit."""
        conn = self._required()
        now = time.time()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if idempotency_key:
                existing = conn.execute(
                    "SELECT * FROM jobs WHERE key_id = ? AND idempotency_key = ?",
                    (key_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if now - float(existing["created_at"]) <= IDEMPOTENCY_SECONDS:
                        conn.execute("COMMIT")
                        return _row(existing), False
                    conn.execute(
                        "UPDATE jobs SET idempotency_key = NULL, updated_at = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
            job_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO jobs (
                    id, key_id, tenant_id, kind, payload, status, result, error,
                    idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', NULL, NULL, ?, ?, ?)
                """,
                (
                    job_id,
                    key_id,
                    tenant_id,
                    kind,
                    json.dumps(payload, separators=(",", ":")),
                    idempotency_key,
                    now,
                    now,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row(row), True

    def get(self, job_id: str, *, key_id: str) -> dict[str, Any] | None:
        row = self._required().execute(
            "SELECT * FROM jobs WHERE id = ? AND key_id = ?",
            (job_id, key_id),
        ).fetchone()
        return None if row is None else _row(row)

    def claim(self) -> dict[str, Any] | None:
        conn = self._required()
        now = time.time()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ? AND status = 'queued'",
                (now, row["id"]),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        return None if claimed is None else _row(claimed)

    def succeed(self, job_id: str, result: dict[str, Any]) -> None:
        self._required().execute(
            "UPDATE jobs SET status = 'succeeded', result = ?, error = NULL, updated_at = ? WHERE id = ?",
            (json.dumps(result, separators=(",", ":")), time.time(), job_id),
        )

    def fail(self, job_id: str, message: str) -> None:
        self._required().execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (message[:500], time.time(), job_id),
        )

    def requeue(self, job_id: str) -> None:
        self._required().execute(
            "UPDATE jobs SET status = 'queued', updated_at = ? WHERE id = ?",
            (time.time(), job_id),
        )

    def _required(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn


class JobRunner:
    def __init__(self, settings, scheduler, artifacts) -> None:
        self.settings = settings
        self.scheduler = scheduler
        self.artifacts = artifacts
        self.store = JobStore(settings.queue_db)
        self._task: asyncio.Task | None = None

    def open(self) -> None:
        self.store.open()

    def close(self) -> None:
        self.store.close()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="job-runner")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def process_one(self) -> bool:
        job = self.store.claim()
        if job is None:
            return False
        try:
            result = await self._run(job)
        except CloudiatorError as exc:
            if exc.code == "metal_busy":
                log.info("job %s deferred: %s", job["id"], exc.message)
                self.store.requeue(job["id"])
                await asyncio.sleep(exc.retry_after or 5)
            else:
                self.store.fail(job["id"], exc.message)
        except Exception as exc:  # noqa: BLE001 - a job failure is a row, not a dead worker
            log.exception("job %s failed", job["id"])
            self.store.fail(job["id"], str(exc) or "job failed")
        else:
            self.store.succeed(job["id"], result)
        return True

    async def _run(self, job: dict[str, Any]) -> dict[str, Any]:
        if job["kind"] != "image":
            raise CloudiatorError(400, "not_supported", "kind must be image.", param="kind")
        from tools.image_generate.handler import generate

        payload = job["payload"]

        async def run() -> dict[str, Any]:
            return await generate(
                payload, settings=self.settings, artifacts=self.artifacts, scheduler=self.scheduler
            )

        return await self.scheduler.run_exclusive("flux", run)

    async def _loop(self) -> None:
        while True:
            try:
                worked = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("job runner pass failed")
                worked = False
            if not worked:
                await asyncio.sleep(POLL_SECONDS)


def public_job(job: dict[str, Any], *, artifacts=None) -> dict[str, Any]:
    body: dict[str, Any] = {"id": job["id"], "status": job["status"], "kind": job["kind"]}
    if job.get("error"):
        body["error"] = job["error"]
    result = job.get("result")
    if isinstance(result, dict):
        shown = dict(result)
        artifact_id = shown.get("id")
        if artifacts is not None and isinstance(artifact_id, str):
            try:
                shown["url"] = artifacts.sign(artifact_id)
            except CloudiatorError:
                shown.pop("url", None)
        body["result"] = shown
    return body


def _row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"]) if row["payload"] else {}
    result = json.loads(row["result"]) if row["result"] else None
    return {
        "id": row["id"],
        "key_id": row["key_id"],
        "tenant_id": row["tenant_id"],
        "kind": row["kind"],
        "payload": payload,
        "status": row["status"],
        "result": result,
        "error": row["error"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
    }
