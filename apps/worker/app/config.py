"""Settings from the environment.

Names and defaults track docs/env.md. Anything that is a budget in PLAN.md §10
(the timeout ladder) is read here once so there is a single place to audit it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

DEFAULT_ARTIFACT_DIR = os.path.expanduser("~/Cloudiator/artifacts")
DEFAULT_QUEUE_DB = os.path.expanduser("~/Cloudiator/queue.db")


def _dashboard_origin() -> str:
    override = _opt("DASHBOARD_ORIGIN")
    if override:
        return override.rstrip("/")
    public = _str("PUBLIC_BASE_URL", "http://127.0.0.1:8080")
    parsed = urlparse(public)
    host = parsed.netloc
    if not host.startswith("api."):
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://app.{host[4:]}"


def _str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _opt(name: str) -> str | None:
    value = os.environ.get(name)
    return None if value is None or value == "" else value


def _int(name: str, default: int) -> int:
    raw = _opt(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = _opt(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _str("CLOUDIATOR_ENV", "development"))
    host: str = field(default_factory=lambda: _str("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8080))
    web_concurrency: str | None = field(default_factory=lambda: _opt("WEB_CONCURRENCY"))
    public_base_url: str = field(
        default_factory=lambda: _str("PUBLIC_BASE_URL", "http://127.0.0.1:8080")
    )
    # Browser playground on app.<domain> (Phase C). Derived from PUBLIC_BASE_URL
    # (api.X → app.X) unless DASHBOARD_ORIGIN is set. Apex callouts do not use CORS.
    dashboard_origin: str = field(default_factory=lambda: _dashboard_origin())

    ollama_host: str = field(default_factory=lambda: _str("OLLAMA_HOST", "http://127.0.0.1:11434"))
    ollama_max_loaded_models: str | None = field(
        default_factory=lambda: _opt("OLLAMA_MAX_LOADED_MODELS")
    )
    default_model: str = field(default_factory=lambda: _str("DEFAULT_MODEL", "gemma4:e4b-it-qat"))
    embed_model: str = field(default_factory=lambda: _str("EMBED_MODEL", "nomic-embed-text"))
    heavy_model: str | None = field(default_factory=lambda: _opt("HEAVY_MODEL"))
    vision_model: str | None = field(default_factory=lambda: _opt("VISION_MODEL"))
    # Set from the Phase A step 0 `ollama show` output (PLAN.md §7). When the
    # default model has no vision capability the image path is OCR-only and a
    # chat request carrying an image_url returns model_not_found.
    default_model_has_vision: bool = field(
        default_factory=lambda: _str("DEFAULT_MODEL_HAS_VISION", "false").lower()
        in ("1", "true", "yes")
    )

    num_ctx: int = field(default_factory=lambda: _int("NUM_CTX", 4096))
    num_ctx_max: int = field(default_factory=lambda: _int("NUM_CTX_MAX", 8192))
    max_tokens_default: int = field(default_factory=lambda: _int("MAX_TOKENS_DEFAULT", 512))

    # PLAN.md §10 timeout ladder. Each layer fails before the one above it.
    sync_deadline_seconds: int = field(default_factory=lambda: _int("SYNC_DEADLINE_SECONDS", 90))
    embeddings_timeout_seconds: int = field(
        default_factory=lambda: _int("EMBEDDINGS_TIMEOUT_SECONDS", 15)
    )
    exclusive_timeout_seconds: int = field(
        default_factory=lambda: _int("EXCLUSIVE_TIMEOUT_SECONDS", 600)
    )
    metal_wait_seconds: float = field(default_factory=lambda: _float("METAL_WAIT_SECONDS", 2.0))

    vision_max_edge_px: int = field(default_factory=lambda: _int("VISION_MAX_EDGE_PX", 1024))
    vision_max_images: int = field(default_factory=lambda: _int("VISION_MAX_IMAGES", 4))
    vision_max_bytes: int = field(default_factory=lambda: _int("VISION_MAX_BYTES", 25 * 1024 * 1024))
    vision_fetch_timeout_seconds: float = field(
        default_factory=lambda: _float("VISION_FETCH_TIMEOUT_SECONDS", 10.0)
    )
    vision_max_redirects: int = field(default_factory=lambda: _int("VISION_MAX_REDIRECTS", 2))

    artifact_dir: str = field(default_factory=lambda: _str("ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR))
    min_free_disk_gb: float = field(default_factory=lambda: _float("MIN_FREE_DISK_GB", 10.0))
    hard_free_disk_gb: float = field(default_factory=lambda: _float("HARD_FREE_DISK_GB", 5.0))
    queue_db: str = field(default_factory=lambda: _str("QUEUE_DB", DEFAULT_QUEUE_DB))

    health_rpm: int = field(default_factory=lambda: _int("HEALTH_RPM", 120))

    # PLAN.md §11. The Mini holds one process for weeks against a Neon compute
    # that auto-suspends after ~5 idle minutes, so the pool is tiny and every
    # socket is treated as possibly dead.
    database_url: str | None = field(default_factory=lambda: _opt("DATABASE_URL"))
    db_pool_min: int = field(default_factory=lambda: _int("DB_POOL_MIN", 0))
    db_pool_max: int = field(default_factory=lambda: _int("DB_POOL_MAX", 2))
    db_connect_timeout_seconds: float = field(
        default_factory=lambda: _float("DB_CONNECT_TIMEOUT_SECONDS", 3.0)
    )
    db_statement_timeout_seconds: float = field(
        default_factory=lambda: _float("DB_STATEMENT_TIMEOUT_SECONDS", 5.0)
    )
    db_pool_recycle_seconds: float = field(
        default_factory=lambda: _float("DB_POOL_RECYCLE_SECONDS", 300.0)
    )

    # Revocation lag equals this value: a flushed cache is the only way to make
    # a revoke immediate (PLAN.md §11).
    key_cache_ttl_seconds: float = field(
        default_factory=lambda: _float("KEY_CACHE_TTL_SECONDS", 60.0)
    )

    usage_flush_interval_seconds: float = field(
        default_factory=lambda: _float("USAGE_FLUSH_INTERVAL_SECONDS", 10.0)
    )
    usage_flush_batch: int = field(default_factory=lambda: _int("USAGE_FLUSH_BATCH", 500))
    usage_outbox_max_rows: int = field(
        default_factory=lambda: _int("USAGE_OUTBOX_MAX_ROWS", 100_000)
    )

    # /v1/admin/* is Cloudflare Access plus JWT validation. ADMIN_TOKEN is a
    # loopback-only break-glass for when Access itself is broken (PLAN.md §12).
    cf_access_team_domain: str | None = field(
        default_factory=lambda: _opt("CF_ACCESS_TEAM_DOMAIN")
    )
    cf_access_aud: str | None = field(default_factory=lambda: _opt("CF_ACCESS_AUD"))
    admin_token: str | None = field(default_factory=lambda: _opt("ADMIN_TOKEN"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
