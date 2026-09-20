"""Test environment.

These must be set before `app.config` is first imported: settings are read once
at import time so a running worker cannot drift from what the gates checked.
"""

from __future__ import annotations

import os
import tempfile
import uuid

_TEST_STATE_DIR = tempfile.mkdtemp(prefix="cloudiator-test-")

# Assigned, not defaulted: a DEFAULT_MODEL or DATABASE_URL left over in the
# operator's shell must not change what the suite proves.
os.environ.update(
    {
        "CLOUDIATOR_ENV": "test",
        "DEFAULT_MODEL": "qwen3.5:9b",
        "EMBED_MODEL": "nomic-embed-text",
        "OLLAMA_MAX_LOADED_MODELS": "2",
        "WEB_CONCURRENCY": "1",
        "NUM_CTX": "4096",
        "MAX_TOKENS_DEFAULT": "512",
        "MIN_FREE_DISK_GB": "0",
        "HARD_FREE_DISK_GB": "0",
        "PUBLIC_BASE_URL": "https://api.cloudiator.test",
        "ARTIFACT_DIR": os.path.join(_TEST_STATE_DIR, "artifacts"),
        # Never the operator's real ~/Cloudiator/queue.db.
        "QUEUE_DB": os.path.join(_TEST_STATE_DIR, "queue.db"),
    }
)
# No Neon from the test suite. A configured URL is opted into per test.
os.environ.pop("DATABASE_URL", None)

import pytest  # noqa: E402

from app.auth import KeyRecord  # noqa: E402
from app.config import get_settings  # noqa: E402

DEFAULT_CAPABILITIES = (
    "chat",
    "embeddings",
    "tools.ocr",
    "tools.maps",
    "tools.charts",
    "tools.stats",
    "tools.data",
    "tools.docs",
    "tools.text",
    "tools.time",
    "tools.image_ops",
)


@pytest.fixture()
def settings():
    return get_settings()


def key_row(**overrides):
    """A row shaped like `SELECT ... FROM api_keys` in Neon."""
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "public_id": "k" + uuid.uuid4().hex[:11],
        "secret_hash": "unused-unless-argon2-runs",
        "name": "test key",
        "preset": "salesforce_engineer",
        "capabilities": list(DEFAULT_CAPABILITIES),
        "models": [],
        "tools": [],
        "max_tokens": 512,
        "max_context": 4096,
        "rpm": 30,
        "daily_token_budget": None,
        "allowed_origins": [],
        "salesforce_org_id": None,
        "log_prompts": False,
        "strip_exif": True,
        "force_no_stream": True,
        "max_response_bytes": 1_048_576,
        "revoked_at": None,
    }
    row.update(overrides)
    return row


def bearer(public_id: str, secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer sk-cld-{public_id}_{secret}"}


class FakeNeon:
    """Neon with a known set of key rows, or an outage.

    `unavailable=True` is the Neon-down drill from the Phase B definition of
    done: cached keys keep working, cache misses become 503s, and usage piles up
    in the outbox.
    """

    def __init__(self, rows=(), *, unavailable: bool = False) -> None:
        self.rows = {row["public_id"]: row for row in rows}
        self.unavailable = unavailable
        self.lookups = 0
        self.inserted: list = []
        self.configured = True

    def state(self) -> str:
        return "degraded" if self.unavailable else "ok"

    async def fetch_api_key(self, public_id: str):
        self.lookups += 1
        if self.unavailable:
            from app.db import DatabaseUnavailable

            raise DatabaseUnavailable("neon is unreachable")
        return self.rows.get(public_id)

    async def insert_usage_events(self, rows) -> None:
        if self.unavailable:
            from app.db import DatabaseUnavailable

            raise DatabaseUnavailable("neon is unreachable")
        self.inserted.extend(rows)

    async def insert_usage_event(self, row) -> None:
        await self.insert_usage_events([row])


@pytest.fixture()
def use_fake_db(monkeypatch):
    """Point the authenticator at a fake Neon and hand it back."""
    from app import main

    def _use(rows=(), *, unavailable: bool = False) -> FakeNeon:
        fake = FakeNeon(rows, unavailable=unavailable)
        monkeypatch.setattr(main.authenticator, "db", fake)
        return fake

    return _use


@pytest.fixture()
def install_key():
    """Put a key straight into the 60s cache and return its auth header.

    A cached key needs neither Neon nor argon2id, which is exactly the Phase B
    invariant: a request with a cached key succeeds with Neon completely down
    (PLAN.md §11).
    """
    from app import main

    def _install(*, secret: str = "test-secret-value", **overrides):
        record = KeyRecord.from_row(key_row(**overrides))
        main.key_cache.put(record.public_id, record, verified_secret=secret)
        return record, bearer(record.public_id, secret)

    return _install


@pytest.fixture()
def cached_key(install_key):
    return install_key()


@pytest.fixture()
def loopback_admin(monkeypatch):
    """Header for the loopback break-glass path on /v1/admin/*.

    Settings are a frozen dataclass on purpose, so the guard gets a replaced copy
    rather than a mutated singleton.
    """
    import dataclasses

    from app import main

    token = "break-glass-token"
    monkeypatch.setattr(
        main.admin_guard, "settings", dataclasses.replace(main.settings, admin_token=token)
    )
    return {"X-Admin-Token": token}


@pytest.fixture()
def make_client():
    """An ASGI client with whatever headers the test needs."""
    import httpx

    from app import main

    def _make(headers: dict[str, str] | None = None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1:8080",
            headers=headers or {},
        )

    return _make


@pytest.fixture(autouse=True)
def reset_worker_state():
    """Per-test isolation for the module-level cache and rate buckets."""
    from app import main

    main.key_cache.flush()
    main.rate_limiter._buckets.clear()
    yield
    main.key_cache.flush()
    main.rate_limiter._buckets.clear()
