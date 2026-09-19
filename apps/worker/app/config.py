"""Settings from the environment.

Names and defaults track docs/env.md. Anything that is a budget in PLAN.md §10
(the timeout ladder) is read here once so there is a single place to audit it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_ARTIFACT_DIR = os.path.expanduser("~/Cloudiator/artifacts")


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
        default_factory=lambda: _str("DEFAULT_MODEL_HAS_VISION", "true").lower()
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

    health_rpm: int = field(default_factory=lambda: _int("HEALTH_RPM", 120))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
