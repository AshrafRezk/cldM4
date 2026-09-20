"""API key authentication (PLAN.md §§10–12).

What must hold, in the order a request meets it:

1. A bad or missing key is a JSON `401`, never an HTML page and never a 500.
2. A cache miss while Neon is unreachable is a `503`, not a `401` — the
   appliance does not know whether the key is good, and "invalid key" sends an
   integrator hunting for a bug that is not theirs.
3. A key that lacks a capability gets `403 scope_denied`; an out-of-scope model
   is a 403 too, not a 404, so the error does not enumerate what is on disk.
4. The per-key `rpm` bucket answers `429` with `Retry-After`.
5. The Authorization header never reaches a log line.
"""

from __future__ import annotations

import logging

import pytest

from app import main
from app.auth import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LEN,
    ARGON2_TIME_COST,
    HASHER,
    KeyRecord,
    RateLimiter,
    hash_secret,
    mint_secret,
    parse_bearer,
    verify_secret,
)
from app.db import SELECT_API_KEY_BY_PUBLIC_ID
from app.errors import CloudiatorError
from app.logging_setup import RedactingFormatter, configure_logging, scrub

from conftest import bearer, key_row

CHAT_BODY = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch):
    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 8,
            "eval_count": 2,
        }

    async def embeddings(model, inputs):
        return [[0.1, 0.2] for _ in inputs]

    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)
    monkeypatch.setattr(main.ollama, "chat", chat)
    monkeypatch.setattr(main.ollama, "embeddings", embeddings)


# ---- key format and hashing ----------------------------------------------


def test_the_documented_argon2id_parameters_are_the_ones_in_use():
    assert (HASHER.time_cost, HASHER.memory_cost, HASHER.parallelism) == (
        ARGON2_TIME_COST,
        ARGON2_MEMORY_COST,
        ARGON2_PARALLELISM,
    )
    assert (HASHER.hash_len, HASHER.salt_len) == (ARGON2_HASH_LEN, ARGON2_SALT_LEN)
    encoded = hash_secret("a-secret")
    assert encoded.startswith("$argon2id$")
    assert "m=65536,t=2,p=1" in encoded


def test_a_minted_key_round_trips_through_the_parser():
    public_id, secret, plaintext = mint_secret()

    assert plaintext == f"sk-cld-{public_id}_{secret}"
    # The separator is the first underscore, so the id must not contain one even
    # though the url-safe secret may.
    assert "_" not in public_id
    assert parse_bearer(f"Bearer {plaintext}") == (public_id, secret)


def test_minted_keys_are_unique():
    assert len({mint_secret()[0] for _ in range(50)}) == 50


def test_verification_accepts_only_the_real_secret():
    _, secret, _ = mint_secret()
    encoded = hash_secret(secret)

    assert verify_secret(encoded, secret) is True
    assert verify_secret(encoded, secret + "x") is False
    assert verify_secret("not-an-argon2-hash", secret) is False


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic abc", "Bearer ", "Bearer sk-live-abc", "Bearer sk-cld-nosecret"],
)
def test_malformed_authorization_headers_are_invalid_api_key(header):
    with pytest.raises(CloudiatorError) as caught:
        parse_bearer(header)

    assert caught.value.status_code == 401
    assert caught.value.code == "invalid_api_key"


# ---- HTTP surface --------------------------------------------------------


async def test_no_key_is_an_openai_shaped_401(make_client):
    async with make_client() as client:
        response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "invalid_api_key"
    assert set(body["error"]) == {"message", "type", "param", "code"}
    assert response.headers["x-request-id"]


async def test_an_unknown_key_is_a_401(make_client, use_fake_db):
    use_fake_db()

    async with make_client(bearer("nosuchkeyxxx", "whatever")) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_the_key_lookup_hides_revoked_keys():
    """A revoked key must be indistinguishable from one that never existed."""
    assert "revoked_at IS NULL" in SELECT_API_KEY_BY_PUBLIC_ID
    assert "public_id = $1" in SELECT_API_KEY_BY_PUBLIC_ID


async def test_the_right_id_with_the_wrong_secret_is_a_401(make_client, use_fake_db):
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    use_fake_db([row])

    async with make_client(bearer(row["public_id"], "not-the-secret")) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_a_key_from_neon_is_verified_and_then_works(make_client, use_fake_db):
    _, secret, _ = mint_secret()
    row = key_row(secret_hash=hash_secret(secret))
    fake = use_fake_db([row])

    async with make_client(bearer(row["public_id"], secret)) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_BODY)
        second = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert (first.status_code, second.status_code) == (200, 200)
    # One lookup for two requests: the second was served from the 60s cache.
    assert fake.lookups == 1


async def test_a_cache_miss_while_neon_is_down_is_a_503_not_a_401(make_client, use_fake_db):
    use_fake_db(unavailable=True)

    async with make_client(bearer("unknownkeyxx", "secret")) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "mini_offline"


async def test_a_cached_key_still_works_with_neon_completely_down(
    make_client, cached_key, use_fake_db
):
    """The Phase B drill: chat must not care that Neon is unreachable."""
    _, headers = cached_key
    fake = use_fake_db(unavailable=True)

    async with make_client(headers) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert response.status_code == 200
    assert fake.lookups == 0


# ---- scopes --------------------------------------------------------------


async def test_a_key_without_the_capability_is_a_403(make_client, install_key):
    _, headers = install_key(capabilities=["chat"])

    async with make_client(headers) as client:
        response = await client.post("/v1/embeddings", json={"input": "hello"})

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "scope_denied"
    assert body["error"]["param"] == "embeddings"


async def test_an_out_of_scope_model_is_a_403_not_a_404(make_client, cached_key):
    """A 403 here refuses to say whether gpt-oss:20b is on disk."""
    _, headers = cached_key

    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions", json={**CHAT_BODY, "model": "gpt-oss:20b"}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_models_lists_only_what_the_key_may_use(make_client, install_key, monkeypatch):
    async def tags():
        return [
            {"name": "qwen3.5:9b"},
            {"name": "nomic-embed-text:latest"},
            {"name": "gpt-oss:20b"},
        ]

    monkeypatch.setattr(main.ollama, "tags", tags)
    _, headers = install_key(capabilities=["chat", "embeddings"])

    async with make_client(headers) as client:
        response = await client.get("/v1/models")

    listed = [item["id"] for item in response.json()["data"]]
    assert "qwen3.5:9b" in listed
    assert "nomic-embed-text:latest" in listed
    assert "gpt-oss:20b" not in listed


async def test_the_key_caps_max_tokens_below_the_request(make_client, install_key, monkeypatch):
    seen: dict[str, object] = {}

    async def chat(model, messages, *, options, tools=None, response_format=None):
        seen.update(options)
        return {"message": {"role": "assistant", "content": "ok"}, "done_reason": "stop"}

    monkeypatch.setattr(main.ollama, "chat", chat)
    _, headers = install_key(max_tokens=64, max_context=2048)

    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 4096},
        )

    assert response.status_code == 200
    assert seen["num_predict"] == 64
    assert seen["num_ctx"] == 2048


# ---- rate limiting -------------------------------------------------------


def test_the_token_bucket_refills_over_time():
    limiter = RateLimiter()
    record = KeyRecord.from_row(key_row(rpm=60))

    for tick in range(60):
        limiter.check(record.key_id, record.rpm, now=1000.0 + tick * 0.001)
    with pytest.raises(CloudiatorError):
        limiter.check(record.key_id, record.rpm, now=1000.1)

    # One token per second at rpm=60.
    limiter.check(record.key_id, record.rpm, now=1002.0)


def test_an_exhausted_bucket_says_how_long_to_wait():
    limiter = RateLimiter()

    limiter.check("key", 1, now=0.0)
    with pytest.raises(CloudiatorError) as caught:
        limiter.check("key", 1, now=0.0)

    assert caught.value.status_code == 429
    assert caught.value.code == "insufficient_quota"
    assert caught.value.retry_after >= 1


async def test_exceeding_rpm_is_a_429_with_retry_after(make_client, install_key):
    _, headers = install_key(rpm=2)

    async with make_client(headers) as client:
        codes = [
            (await client.post("/v1/chat/completions", json=CHAT_BODY)).status_code
            for _ in range(3)
        ]
        limited = await client.post("/v1/chat/completions", json=CHAT_BODY)

    assert codes == [200, 200, 429]
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "insufficient_quota"
    assert int(limited.headers["retry-after"]) >= 1


def test_idle_buckets_are_purged():
    limiter = RateLimiter()
    limiter.check("key", 30, now=0.0)

    assert limiter.purge_idle(now=10_000.0) == 1


# ---- logging -------------------------------------------------------------


async def test_the_authorization_header_never_reaches_a_log_line(
    make_client, use_fake_db, caplog
):
    use_fake_db()
    secret = "super-secret-value-that-must-not-be-logged"

    with caplog.at_level(logging.DEBUG):
        async with make_client(bearer("loggedkeyxxx", secret)) as client:
            await client.post("/v1/chat/completions", json=CHAT_BODY)

    text = caplog.text
    assert secret not in text
    assert "sk-cld-loggedkeyxxx" not in text


def test_scrubbing_covers_the_header_the_key_and_the_dsn():
    scrubbed = scrub(
        "Authorization: Bearer sk-cld-abc_def and sk-cld-other_secret and "
        "postgresql://user:pw@ep-x-pooler.eu-west-2.aws.neon.tech/neondb"
    )

    assert "sk-cld-abc_def" not in scrubbed
    assert "sk-cld-other_secret" not in scrubbed
    assert "user:pw" not in scrubbed
    # The host survives, because an unreadable connection error is its own outage.
    assert "ep-x-pooler.eu-west-2.aws.neon.tech" in scrubbed


def test_a_traceback_is_scrubbed_too():
    """`logging` renders exc_info after filters run, so the formatter has to."""
    formatter = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError("failed with Authorization: Bearer sk-cld-abc_supersecret")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "boom", None, sys.exc_info()
        )

    rendered = formatter.format(record)
    assert "supersecret" not in rendered
    assert "[redacted]" in rendered


def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()
    root = logging.getLogger()

    for handler in root.handlers:
        assert isinstance(handler.formatter, RedactingFormatter)
