"""API keys: minting, verification, caching, and per-key rate limits.

The worker is the only authenticator in v1 (PLAN.md §2). Cloudflare does TLS,
DDoS, and a WAF skip rule; it never sees a key. So everything a caller can do
wrong has to produce an OpenAI-shaped error here.

Three rules from PLAN.md §§11–12 that shape this file:

* **argon2id with written-down parameters** (t=2, m=64 MiB, p=1, hash_len=32,
  salt_len=16), looked up by the indexed `public_id`, verified with the
  library's constant-time verify. Never `==` on a hash.
* **A 60s cache, positive and negative**, keyed on a fast hash of the presented
  secret. 64 MiB per verification next to a 7 GB resident model is a recurring
  RAM spike, so argon2id must not run on every request. The price is that
  revocation takes up to 60s, which the dashboard has to say out loud, and
  `POST /v1/admin/cache/flush` is the override.
* **Neon is never on the critical path.** A request whose key is already cached
  succeeds with Neon completely down. A cache miss while Neon is unreachable is
  a `503 mini_offline`, never a `401` — the appliance does not know whether the
  key is good, and saying "invalid key" would send an integrator hunting for a
  bug that is not theirs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerificationError

from .db import DatabaseUnavailable
from .errors import CloudiatorError, invalid_api_key, mini_offline, rate_limited, scope_denied
from .ollama import normalize_tag

log = logging.getLogger("cloudiator.auth")

KEY_PREFIX = "sk-cld-"
# No underscore: the plaintext is sk-cld-{public_id}_{secret} and the secret is
# url-safe base64, which may contain one.
PUBLIC_ID_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789"
PUBLIC_ID_LENGTH = 12
SECRET_BYTES = 32

# PLAN.md §12. Changing these silently invalidates nothing (argon2 encodes its
# parameters in the hash), but it does change the cost of every verification.
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 65536  # KiB, i.e. 64 MiB
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

HASHER = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
)

# Bounded so a caller hammering one public_id with random secrets cannot grow
# the cache entry without limit.
MAX_VERIFIED_DIGESTS = 8
MAX_REJECTED_DIGESTS = 64
RATE_BUCKET_IDLE_SECONDS = 600.0


def mint_secret() -> tuple[str, str, str]:
    """Return (public_id, secret, plaintext). The plaintext is shown once."""
    public_id = "".join(secrets.choice(PUBLIC_ID_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))
    secret = secrets.token_urlsafe(SECRET_BYTES)
    return public_id, secret, f"{KEY_PREFIX}{public_id}_{secret}"


def hash_secret(secret: str) -> str:
    return HASHER.hash(secret)


def verify_secret(secret_hash: str, secret: str) -> bool:
    """argon2id's own constant-time verify. Never compare hashes directly."""
    try:
        return HASHER.verify(secret_hash, secret)
    except (VerificationError, InvalidHashError):
        return False
    except Argon2Error as exc:  # malformed stored hash, wrong parameters
        log.error("argon2 could not verify a stored hash: %s", exc)
        return False


def parse_bearer(header: str | None) -> tuple[str, str]:
    """Split `Authorization: Bearer sk-cld-<public_id>_<secret>`.

    The header value never reaches a log line or an error body.
    """
    if not header:
        raise invalid_api_key("No API key provided. Send Authorization: Bearer sk-cld-...")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise invalid_api_key("Authorization must be 'Bearer sk-cld-...'.")
    token = value.strip()
    if not token.startswith(KEY_PREFIX):
        raise invalid_api_key("An API key starts with sk-cld-.")
    public_id, separator, secret = token[len(KEY_PREFIX) :].partition("_")
    if not separator or not public_id or not secret:
        raise invalid_api_key("Malformed API key. The shape is sk-cld-<id>_<secret>.")
    return public_id, secret


def _as_list(value: Any) -> list[str]:
    """Neon hands back jsonb as a string when no codec is registered."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


@dataclass(frozen=True)
class KeyRecord:
    key_id: str
    tenant_id: str
    public_id: str
    secret_hash: str
    name: str
    preset: str | None
    capabilities: frozenset[str]
    models: tuple[str, ...]
    tools: tuple[str, ...]
    max_tokens: int
    max_context: int
    rpm: int
    daily_token_budget: int | None
    allowed_origins: tuple[str, ...]
    salesforce_org_id: str | None
    log_prompts: bool
    strip_exif: bool
    force_no_stream: bool
    max_response_bytes: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "KeyRecord":
        return cls(
            key_id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            public_id=row["public_id"],
            secret_hash=row["secret_hash"],
            name=row.get("name") or "",
            preset=row.get("preset"),
            capabilities=frozenset(_as_list(row.get("capabilities"))),
            models=tuple(_as_list(row.get("models"))),
            tools=tuple(_as_list(row.get("tools"))),
            max_tokens=int(row.get("max_tokens") or 512),
            max_context=int(row.get("max_context") or 4096),
            rpm=int(row.get("rpm") or 30),
            daily_token_budget=row.get("daily_token_budget"),
            allowed_origins=tuple(_as_list(row.get("allowed_origins"))),
            salesforce_org_id=row.get("salesforce_org_id"),
            log_prompts=bool(row.get("log_prompts")),
            strip_exif=bool(row.get("strip_exif", True)),
            force_no_stream=bool(row.get("force_no_stream")),
            max_response_bytes=int(row.get("max_response_bytes") or 1_048_576),
        )

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def allowed_models(self, settings) -> set[str]:
        """Empty `models` means the default model only (docs/schema.md)."""
        allowed = {normalize_tag(model) for model in self.models}
        if not allowed:
            allowed = {normalize_tag(settings.default_model)}
        if self.has("embeddings"):
            allowed.add(normalize_tag(settings.embed_model))
        return allowed


@dataclass
class _Entry:
    """A cached lookup. `record is None` is the negative case."""

    record: KeyRecord | None
    expires_at: float
    verified: set[bytes] = field(default_factory=set)
    rejected: set[bytes] = field(default_factory=set)


class KeyCache:
    """60s positive and negative cache, keyed by public_id (PLAN.md §11).

    Secrets are never stored. What is stored is a keyed blake2b digest of the
    secret that was presented, so a repeat request can be answered with a
    constant-time comparison instead of a 64 MiB argon2id verification — and so
    a caller replaying a wrong secret cannot use argon2 as an amplifier either.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        # Per-process, so a digest is meaningless outside this worker.
        self._salt = secrets.token_bytes(32)
        self.hits = 0
        self.misses = 0
        self.argon2_verifications = 0

    def digest(self, secret: str) -> bytes:
        return hashlib.blake2b(secret.encode("utf-8"), key=self._salt, digest_size=32).digest()

    def _live(self, public_id: str, now: float) -> _Entry | None:
        entry = self._entries.get(public_id)
        if entry is None:
            return None
        if entry.expires_at <= now:
            self._entries.pop(public_id, None)
            return None
        return entry

    def get(self, public_id: str, *, now: float | None = None) -> _Entry | None:
        entry = self._live(public_id, time.monotonic() if now is None else now)
        if entry is None:
            self.misses += 1
        else:
            self.hits += 1
        return entry

    def put(
        self,
        public_id: str,
        record: KeyRecord | None,
        *,
        verified_secret: str | None = None,
        now: float | None = None,
    ) -> _Entry:
        now = time.monotonic() if now is None else now
        entry = _Entry(record=record, expires_at=now + self.ttl)
        if verified_secret is not None:
            entry.verified.add(self.digest(verified_secret))
        self._entries[public_id] = entry
        return entry

    def mark_verified(self, entry: _Entry, secret: str) -> None:
        if len(entry.verified) >= MAX_VERIFIED_DIGESTS:
            entry.verified.clear()
        entry.verified.add(self.digest(secret))

    def mark_rejected(self, entry: _Entry, secret: str) -> None:
        if len(entry.rejected) >= MAX_REJECTED_DIGESTS:
            entry.rejected.clear()
        entry.rejected.add(self.digest(secret))

    def matches(self, digests: Iterable[bytes], secret: str) -> bool:
        candidate = self.digest(secret)
        found = False
        for digest in digests:
            # No early exit: compare every entry so the answer does not depend
            # on where in the set a match happens to sit.
            if hmac.compare_digest(digest, candidate):
                found = True
        return found

    def flush(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        return count

    def forget(self, public_id: str) -> None:
        self._entries.pop(public_id, None)

    def purge_expired(self, *, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        stale = [pid for pid, entry in self._entries.items() if entry.expires_at <= now]
        for pid in stale:
            self._entries.pop(pid, None)
        return len(stale)

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "argon2_verifications": self.argon2_verifications,
        }


class RateLimiter:
    """Per-key token bucket (PLAN.md §10).

    In-process, so it resets on a worker restart. That is documented and
    accepted: the alternative is Redis on an appliance that is meant to survive
    a power cut with no moving parts. The Cloudflare rule in front of it is DDoS
    insurance, not this.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, key_id: str, rpm: int, *, now: float | None = None) -> None:
        if rpm <= 0:
            return
        now = time.monotonic() if now is None else now
        tokens, updated = self._buckets.get(key_id, (float(rpm), now))
        tokens = min(float(rpm), tokens + (now - updated) * (rpm / 60.0))
        if tokens < 1.0:
            self._buckets[key_id] = (tokens, now)
            retry_after = max(1, math.ceil((1.0 - tokens) / (rpm / 60.0)))
            raise rate_limited(
                f"This key is limited to {rpm} requests per minute.", retry_after=retry_after
            )
        self._buckets[key_id] = (tokens - 1.0, now)

    def purge_idle(self, *, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        stale = [
            key
            for key, (_, updated) in self._buckets.items()
            if now - updated > RATE_BUCKET_IDLE_SECONDS
        ]
        for key in stale:
            self._buckets.pop(key, None)
        return len(stale)


class Authenticator:
    def __init__(self, settings, db, cache: KeyCache) -> None:
        self.settings = settings
        self.db = db
        self.cache = cache

    async def authenticate(self, authorization: str | None) -> KeyRecord:
        public_id, secret = parse_bearer(authorization)
        entry = self.cache.get(public_id)

        if entry is None:
            entry = await self._load(public_id, secret)
        if entry.record is None:
            raise invalid_api_key("This API key is not valid or has been revoked.")

        if self.cache.matches(entry.verified, secret):
            return entry.record
        if self.cache.matches(entry.rejected, secret):
            raise invalid_api_key("This API key is not valid or has been revoked.")

        if await self._verify(entry.record.secret_hash, secret):
            self.cache.mark_verified(entry, secret)
            return entry.record
        self.cache.mark_rejected(entry, secret)
        raise invalid_api_key("This API key is not valid or has been revoked.")

    async def _load(self, public_id: str, secret: str) -> _Entry:
        try:
            row = await self.db.fetch_api_key(public_id)
        except DatabaseUnavailable as exc:
            # Not a 401: we do not know whether this key is good, and telling an
            # integrator their key is invalid during a Neon outage costs a day.
            log.warning("key lookup failed while Neon is unreachable: %s", exc)
            raise mini_offline(
                "The appliance cannot reach its key store right now. Keys already in use "
                "keep working; retry shortly."
            ) from exc
        if row is None:
            return self.cache.put(public_id, None)

        record = KeyRecord.from_row(row)
        if await self._verify(record.secret_hash, secret):
            return self.cache.put(public_id, record, verified_secret=secret)
        entry = self.cache.put(public_id, record)
        self.cache.mark_rejected(entry, secret)
        return entry

    async def _verify(self, secret_hash: str, secret: str) -> bool:
        """argon2id off the event loop: 64 MiB and ~50ms is not a coroutine."""
        self.cache.argon2_verifications += 1
        return await asyncio.to_thread(verify_secret, secret_hash, secret)


def require_capability(record: KeyRecord, capability: str) -> None:
    if not record.has(capability):
        raise scope_denied(
            f"This key does not have the {capability!r} capability. "
            "Scopes are set on the key in the dashboard.",
            param=capability,
        )


def enforce_model_scope(record: KeyRecord, model: str, settings) -> None:
    """Scope is checked before "is it on disk" so the 403 leaks nothing."""
    if normalize_tag(model) not in record.allowed_models(settings):
        raise scope_denied(
            f"This key may not use {model!r}. GET /v1/models lists what it can use.",
            param="model",
        )


def clamp_max_tokens(requested: int, record: KeyRecord) -> int:
    return min(requested, record.max_tokens)


def effective_context(record: KeyRecord, num_ctx: int) -> int:
    return min(num_ctx, record.max_context)


__all__ = [
    "Authenticator",
    "CloudiatorError",
    "KeyCache",
    "KeyRecord",
    "RateLimiter",
    "clamp_max_tokens",
    "effective_context",
    "enforce_model_scope",
    "hash_secret",
    "mint_secret",
    "parse_bearer",
    "require_capability",
    "verify_secret",
]
