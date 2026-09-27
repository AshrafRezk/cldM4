"""A queued job is still there after the store is closed and reopened."""

from __future__ import annotations

from app.jobs import JobStore


def _enqueue(store: JobStore) -> str:
    job, created = store.enqueue(
        key_id="key-a",
        tenant_id="t",
        kind="image",
        payload={"prompt": "a red bicycle", "width": 1024, "height": 1024, "steps": 4, "seed": None},
        idempotency_key=None,
    )
    assert created is True
    return job["id"]


def test_a_queued_job_survives_reopen(tmp_path):
    path = str(tmp_path / "queue.db")
    store = JobStore(path)
    store.open()
    job_id = _enqueue(store)
    store.close()

    reopened = JobStore(path)
    reopened.open()
    found = reopened.get(job_id, key_id="key-a")
    assert found is not None
    assert found["status"] == "queued"
    assert found["payload"]["prompt"] == "a red bicycle"
    assert reopened.get(job_id, key_id="someone-else") is None


def test_a_running_job_is_queued_again_after_reopen(tmp_path):
    path = str(tmp_path / "queue.db")
    store = JobStore(path)
    store.open()
    job_id = _enqueue(store)
    claimed = store.claim()
    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    store.close()

    reopened = JobStore(path)
    reopened.open()
    found = reopened.get(job_id, key_id="key-a")
    assert found is not None
    assert found["status"] == "queued"
