"""The 60s key cache (PLAN.md §§11–12).

The cache is not a latency optimisation first. argon2id at 64 MiB per
verification, on every request, is a recurring RAM spike sitting next to a 7 GB
resident model — so the cache exists to keep it off the hot path, positive and
negative.

Its cost is the thing to test as carefully as its benefit: **revocation takes up
to the TTL to take effect**, which is why the dashboard has to say so and why
`POST /v1/admin/cache/flush` exists.
"""

from __future__ import annotations

import pytest

from app import main
from app.auth import Authenticator, KeyCache, KeyRecord, hash_secret, mint_secret
from app.errors import CloudiatorError

from conftest import FakeNeon, bearer, key_row

CHAT_BODY = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch):
    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {"message": {"role": "assistant", "content": "hi"}, "done_reason": "stop"}

    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)
    monkeypatch.setattr(main.ollama, "chat", chat)


def make_authenticator(rows=(), *, ttl: float = 60.0, unavailable: bool = False):
    cache = KeyCache(ttl)
    db = FakeNeon(rows, unavailable=unavailable)
    return Authenticator(main.settings, db, cache), cache, db


async def test_a_verified_key_pays_for_argon2_once():
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    auth, cache, db = make_authenticator([row])
    header = bearer(row["public_id"], secret)["Authorization"]

    for _ in range(5):
        assert (await auth.authenticate(header)).public_id == row["public_id"]

    assert db.lookups == 1
    assert cache.argon2_verifications == 1


async def test_a_wrong_secret_is_not_an_argon2_amplifier():
    """A caller replaying a bad secret must not cost 64 MiB every time."""
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    auth, cache, _ = make_authenticator([row])
    header = bearer(row["public_id"], "wrong-secret")["Authorization"]

    for _ in range(5):
        with pytest.raises(CloudiatorError):
            await auth.authenticate(header)

    assert cache.argon2_verifications == 1


async def test_a_wrong_secret_does_not_poison_the_right_one():
    """The negative case is per secret, not per public_id."""
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    auth, _, _ = make_authenticator([row])

    with pytest.raises(CloudiatorError):
        await auth.authenticate(bearer(row["public_id"], "wrong")["Authorization"])
    record = await auth.authenticate(bearer(row["public_id"], secret)["Authorization"])

    assert record.public_id == row["public_id"]


async def test_an_unknown_key_is_cached_negatively():
    auth, _, db = make_authenticator()
    header = bearer("nosuchkeyxxx", "whatever")["Authorization"]

    for _ in range(4):
        with pytest.raises(CloudiatorError) as caught:
            await auth.authenticate(header)
        assert caught.value.status_code == 401

    # One Neon round trip for four attempts: a key-guessing flood does not
    # become a query flood.
    assert db.lookups == 1


async def test_the_entry_expires_after_the_ttl():
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    auth, cache, db = make_authenticator([row], ttl=0.0)
    header = bearer(row["public_id"], secret)["Authorization"]

    await auth.authenticate(header)
    await auth.authenticate(header)

    assert db.lookups == 2


async def test_revocation_takes_effect_when_the_entry_expires():
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    auth, cache, db = make_authenticator([row])
    header = bearer(row["public_id"], secret)["Authorization"]

    await auth.authenticate(header)
    db.rows.clear()  # revoked in Neon

    # Still accepted: this is the documented revocation lag.
    await auth.authenticate(header)

    cache.flush()
    with pytest.raises(CloudiatorError) as caught:
        await auth.authenticate(header)
    assert caught.value.status_code == 401


def test_flush_reports_what_it_dropped():
    cache = KeyCache(60.0)
    cache.put("a", KeyRecord.from_row(key_row(public_id="a")), verified_secret="s")
    cache.put("b", None)

    assert cache.flush() == 2
    assert cache.get("a") is None


def test_purge_expired_only_drops_stale_entries():
    cache = KeyCache(10.0)
    cache.put("fresh", None, now=100.0)
    cache.put("stale", None, now=0.0)

    assert cache.purge_expired(now=100.0) == 1
    assert cache.get("fresh", now=100.0) is not None


def test_a_digest_never_contains_the_secret():
    cache = KeyCache(60.0)
    secret = "a-secret-that-must-not-be-stored"

    digest = cache.digest(secret)

    assert secret.encode() not in digest
    assert len(digest) == 32
    assert cache.matches([digest], secret) is True
    assert cache.matches([digest], secret + "x") is False


def test_two_caches_produce_different_digests():
    """Per-process salt: a digest is meaningless outside the worker that made it."""
    secret = "same-secret"

    assert KeyCache(60.0).digest(secret) != KeyCache(60.0).digest(secret)


def test_the_cache_stays_bounded_under_a_key_guessing_flood():
    """And a verified key survives it: re-verifying costs 64 MiB of argon2id."""
    from app.auth import MAX_CACHE_ENTRIES

    cache = KeyCache(60.0)
    real = KeyRecord.from_row(key_row(public_id="realkey"))
    cache.put("realkey", real, verified_secret="s", now=0.0)

    for index in range(MAX_CACHE_ENTRIES * 2):
        cache.put(f"guess-{index}", None, now=0.0)

    assert len(cache._entries) <= MAX_CACHE_ENTRIES
    entry = cache.get("realkey", now=0.0)
    assert entry is not None and entry.record is real


def test_the_verified_and_rejected_sets_are_bounded():
    cache = KeyCache(60.0)
    entry = cache.put("bounded", KeyRecord.from_row(key_row(public_id="bounded")))

    for index in range(500):
        cache.mark_rejected(entry, f"secret-{index}")
        cache.mark_verified(entry, f"good-{index}")

    assert len(entry.rejected) <= 64
    assert len(entry.verified) <= 8


async def test_admin_cache_flush_makes_a_revocation_immediate(
    make_client, cached_key, use_fake_db, loopback_admin
):
    _, headers = cached_key
    db = use_fake_db()

    async with make_client(headers) as client:
        assert (await client.post("/v1/chat/completions", json=CHAT_BODY)).status_code == 200

        flushed = await client.post("/v1/admin/cache/flush", headers=loopback_admin)
        assert flushed.status_code == 200
        assert flushed.json()["flushed"] >= 1

        # Neon no longer has the key, and the cache no longer covers for it.
        after = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert after.status_code == 401
    assert db.lookups == 1
