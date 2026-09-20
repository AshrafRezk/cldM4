"""The usage outbox (PLAN.md §11).

A usage write is not allowed to cost a request. The rules under test:

* The request path writes to local SQLite, never to Neon, and swallows its own
  failures.
* A chat succeeds with Neon completely down, and the row waits in the outbox.
* The flusher drains in batches of 500, deletes only what Neon accepted, and
  leaves the rest queued.
* At 100k rows the oldest are dropped and the drop is logged. A full SSD takes
  down Ollama, the worker, and cloudflared at once, so metrics lose.
* `outbox_depth` is in /v1/health, because a depth that only grows is the one
  signal that Neon has been unreachable for a while.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3

import pytest

from app import main
from app.usage import UsageEvent, UsageOutbox

from conftest import FakeNeon

CHAT_BODY = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch):
    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "eval_count": 3,
        }

    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)
    monkeypatch.setattr(main.ollama, "chat", chat)


def make_outbox(tmp_path, db, **overrides) -> UsageOutbox:
    settings = dataclasses.replace(
        main.settings, queue_db=str(tmp_path / "queue.db"), **overrides
    )
    outbox = UsageOutbox(settings, db)
    outbox.open()
    return outbox


def event(**overrides) -> UsageEvent:
    fields = {
        "route": "/v1/chat/completions",
        "status": 200,
        "request_id": "req-1",
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "model": "qwen3.5:9b",
        "latency_ms": 42,
        "prompt_tokens": 11,
        "completion_tokens": 3,
        "bytes_out": 128,
    }
    fields.update(overrides)
    return UsageEvent(**fields)


def test_the_ddl_matches_infra_queue_sqlite_sql():
    """One shape for the outbox table, whether the worker or an operator made it."""
    import re
    from pathlib import Path

    from app.usage import OUTBOX_DDL

    reference = (Path(__file__).resolve().parents[3] / "infra" / "queue.sqlite.sql").read_text()

    def columns(sql: str) -> list[str]:
        body = re.search(r"CREATE TABLE IF NOT EXISTS usage_outbox \((.*?)\);", sql, re.S)
        assert body, "no usage_outbox DDL"
        return [" ".join(line.split()) for line in body.group(1).strip().splitlines()]

    assert columns(OUTBOX_DDL) == columns(reference)


def test_a_row_is_written_locally_and_counted(tmp_path):
    outbox = make_outbox(tmp_path, FakeNeon())
    try:
        outbox.record(event())

        assert outbox.depth() == 1
        rows = sqlite3.connect(outbox.path).execute("SELECT payload FROM usage_outbox").fetchall()
        payload = json.loads(rows[0][0])
        assert payload["route"] == "/v1/chat/completions"
        assert payload["ts"]
    finally:
        outbox.close()


def test_the_queue_survives_a_restart(tmp_path):
    first = make_outbox(tmp_path, FakeNeon())
    first.record(event())
    first.close()

    second = make_outbox(tmp_path, FakeNeon())
    try:
        assert second.depth() == 1
    finally:
        second.close()


def test_health_checks_are_not_recorded(tmp_path):
    outbox = make_outbox(tmp_path, FakeNeon())
    try:
        outbox.record(event(route="/v1/health", status=200))

        assert outbox.depth() == 0
    finally:
        outbox.close()


def test_an_unauthenticated_request_is_not_recorded(tmp_path):
    """A 401 flood from the public internet must not fill the outbox."""
    outbox = make_outbox(tmp_path, FakeNeon())
    try:
        outbox.record(event(key_id=None, status=401))

        assert outbox.depth() == 0
    finally:
        outbox.close()


def test_recording_never_raises_when_sqlite_is_gone(tmp_path, caplog):
    outbox = make_outbox(tmp_path, FakeNeon())
    outbox._conn.close()  # simulate a broken database handle

    with caplog.at_level(logging.WARNING):
        outbox.record(event())

    assert "could not queue a usage row" in caplog.text


async def test_a_flush_sends_rows_and_empties_the_queue(tmp_path):
    db = FakeNeon()
    outbox = make_outbox(tmp_path, db)
    try:
        for index in range(3):
            outbox.record(event(request_id=f"req-{index}"))

        assert await outbox.flush_once() == 3
        assert outbox.depth() == 0
        assert len(db.inserted) == 3
        # ts survives as a timestamp, so the row says when the call happened, not
        # when the flush did.
        assert db.inserted[0][2].tzinfo is not None
    finally:
        outbox.close()


async def test_rows_stay_queued_while_neon_is_down(tmp_path):
    db = FakeNeon(unavailable=True)
    outbox = make_outbox(tmp_path, db)
    try:
        outbox.record(event())

        assert await outbox.flush_once() == 0
        assert outbox.depth() == 1
        assert db.inserted == []

        db.unavailable = False
        assert await outbox.flush_once() == 1
        assert outbox.depth() == 0
    finally:
        outbox.close()


async def test_a_long_outage_does_not_discard_good_rows(tmp_path):
    """Attempts are counted, not used as a give-up threshold."""
    db = FakeNeon(unavailable=True)
    outbox = make_outbox(tmp_path, db)
    try:
        outbox.record(event())
        for _ in range(10):
            await outbox.flush_once()

        assert outbox.depth() == 1
        attempts = sqlite3.connect(outbox.path).execute(
            "SELECT attempts FROM usage_outbox"
        ).fetchone()[0]
        assert attempts == 10
    finally:
        outbox.close()


async def test_a_row_neon_refuses_does_not_wedge_the_queue(tmp_path, caplog):
    class RefusingNeon(FakeNeon):
        async def insert_usage_events(self, rows):
            from app.db import DatabaseRejected

            if len(rows) > 1:
                raise DatabaseRejected("foreign key violation")
            await super().insert_usage_events(rows)

        async def insert_usage_event(self, row):
            from app.db import DatabaseRejected

            if row[3] == "poison":
                raise DatabaseRejected("foreign key violation")
            await super().insert_usage_events([row])

    db = RefusingNeon()
    outbox = make_outbox(tmp_path, db)
    try:
        outbox.record(event(request_id="poison"))
        outbox.record(event(request_id="fine"))

        with caplog.at_level(logging.WARNING):
            assert await outbox.flush_once() == 2

        assert outbox.depth() == 0
        assert [row[3] for row in db.inserted] == ["fine"]
        assert outbox.dropped() == 1
        assert "refused" in caplog.text
    finally:
        outbox.close()


async def test_the_flusher_drains_in_batches(tmp_path):
    db = FakeNeon()
    outbox = make_outbox(tmp_path, db, usage_flush_batch=5)
    try:
        for index in range(12):
            outbox.record(event(request_id=f"req-{index}"))

        assert await outbox.flush_once() == 12
        assert outbox.depth() == 0
        assert len(db.inserted) == 12
    finally:
        outbox.close()


def test_the_cap_drops_the_oldest_rows_and_logs_it(tmp_path, caplog):
    outbox = make_outbox(tmp_path, FakeNeon(), usage_outbox_max_rows=5)
    try:
        with caplog.at_level(logging.WARNING):
            for index in range(9):
                outbox.record(event(request_id=f"req-{index}"))

        assert outbox.depth() == 5
        assert outbox.dropped() == 4
        assert "row cap" in caplog.text

        kept = [
            json.loads(row[0])["request_id"]
            for row in sqlite3.connect(outbox.path)
            .execute("SELECT payload FROM usage_outbox ORDER BY id")
            .fetchall()
        ]
        assert kept == [f"req-{index}" for index in range(4, 9)]
    finally:
        outbox.close()


async def test_a_chat_still_succeeds_with_neon_down_and_queues_its_usage(
    tmp_path, make_client, cached_key, use_fake_db, monkeypatch
):
    """The Phase B Neon-down drill, end to end through the HTTP surface."""
    _, headers = cached_key
    use_fake_db(unavailable=True)
    outbox = make_outbox(tmp_path, FakeNeon(unavailable=True))
    monkeypatch.setattr(main, "outbox", outbox)
    try:
        async with make_client(headers) as client:
            chat = await client.post("/v1/chat/completions", json=CHAT_BODY)
            health = await client.get("/v1/health")

        assert chat.status_code == 200
        assert outbox.depth() == 1
        body = health.json()
        assert body["outbox_depth"] == 1
        # Health answers 200 with a degraded db rather than failing (PLAN.md §10).
        assert health.status_code == 200
    finally:
        outbox.close()


async def test_the_recorded_row_carries_the_key_tokens_and_request_id(
    tmp_path, make_client, cached_key, use_fake_db, monkeypatch
):
    record, headers = cached_key
    use_fake_db()
    outbox = make_outbox(tmp_path, FakeNeon())
    monkeypatch.setattr(main, "outbox", outbox)
    try:
        async with make_client(headers) as client:
            response = await client.post(
                "/v1/chat/completions", json=CHAT_BODY, headers={"X-Request-Id": "req-abc"}
            )

        assert response.status_code == 200
        payload = json.loads(
            sqlite3.connect(outbox.path).execute("SELECT payload FROM usage_outbox").fetchone()[0]
        )
        assert payload["key_id"] == record.key_id
        assert payload["tenant_id"] == record.tenant_id
        assert payload["request_id"] == "req-abc"
        assert payload["route"] == "/v1/chat/completions"
        assert payload["status"] == 200
        assert payload["model"] == "qwen3.5:9b"
        assert payload["prompt_tokens"] == 11
        assert payload["completion_tokens"] == 3
        assert payload["latency_ms"] is not None
    finally:
        outbox.close()


async def test_an_error_response_records_its_error_code(
    tmp_path, make_client, cached_key, use_fake_db, monkeypatch
):
    _, headers = cached_key
    use_fake_db()
    outbox = make_outbox(tmp_path, FakeNeon())
    monkeypatch.setattr(main, "outbox", outbox)
    try:
        async with make_client(headers) as client:
            response = await client.post(
                "/v1/chat/completions", json={**CHAT_BODY, "model": "gpt-oss:20b"}
            )

        assert response.status_code == 403
        payload = json.loads(
            sqlite3.connect(outbox.path).execute("SELECT payload FROM usage_outbox").fetchone()[0]
        )
        assert payload["status"] == 403
        assert payload["error_code"] == "scope_denied"
    finally:
        outbox.close()
