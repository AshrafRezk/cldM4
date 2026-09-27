"""Idempotency-Key returns the original job for 24h (PLAN.md §10)."""

from __future__ import annotations

import time

from app.jobs import JobStore


def test_repeat_key_returns_the_original_job(tmp_path):
    store = JobStore(str(tmp_path / "queue.db"))
    store.open()
    first, created = store.enqueue(
        key_id="key-a", tenant_id="t", kind="image", payload={"prompt": "a red bicycle"}, idempotency_key="test-1"
    )
    second, again = store.enqueue(
        key_id="key-a", tenant_id="t", kind="image", payload={"prompt": "different"}, idempotency_key="test-1"
    )
    assert created is True
    assert again is False
    assert second["id"] == first["id"]
    assert second["payload"]["prompt"] == "a red bicycle"


def test_the_same_header_on_another_key_is_a_new_job(tmp_path):
    store = JobStore(str(tmp_path / "queue.db"))
    store.open()
    first, _ = store.enqueue(
        key_id="key-a", tenant_id="t", kind="image", payload={"prompt": "a"}, idempotency_key="test-1"
    )
    second, created = store.enqueue(
        key_id="key-b", tenant_id="t", kind="image", payload={"prompt": "b"}, idempotency_key="test-1"
    )
    assert created is True
    assert second["id"] != first["id"]


def test_a_key_older_than_a_day_can_be_reused(tmp_path):
    store = JobStore(str(tmp_path / "queue.db"))
    store.open()
    first, _ = store.enqueue(
        key_id="key-a", tenant_id="t", kind="image", payload={"prompt": "a"}, idempotency_key="test-1"
    )
    store._required().execute(
        "UPDATE jobs SET created_at = ? WHERE id = ?",
        (time.time() - (25 * 60 * 60), first["id"]),
    )
    second, created = store.enqueue(
        key_id="key-a", tenant_id="t", kind="image", payload={"prompt": "b"}, idempotency_key="test-1"
    )
    assert created is True
    assert second["id"] != first["id"]


async def test_http_replay_returns_200_and_the_same_id(make_client, install_key, monkeypatch):
    from app import main

    async def fake_run(job):
        return {"id": "abc", "url": "https://api.cloudiator.test/artifacts/abc"}

    monkeypatch.setattr(main.jobs, "_run", fake_run)
    _record, headers = install_key(capabilities=["image_generation"])
    body = {"kind": "image", "prompt": "a red bicycle"}
    async with make_client(headers) as client:
        first = await client.post("/v1/jobs", json=body, headers={"Idempotency-Key": "test-1"})
        second = await client.post("/v1/jobs", json=body, headers={"Idempotency-Key": "test-1"})
    assert first.status_code == 202, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]


async def test_a_salesforce_engineer_key_cannot_enqueue_flux(make_client, install_key):
    _record, headers = install_key()
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/jobs", json={"kind": "image", "prompt": "a red bicycle"}
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"
