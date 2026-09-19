"""Test environment.

These must be set before `app.config` is first imported: settings are read once
at import time so a running worker cannot drift from what the gates checked.
"""

from __future__ import annotations

import os

os.environ.setdefault("CLOUDIATOR_ENV", "test")
os.environ.setdefault("DEFAULT_MODEL", "qwen3.5:9b")
os.environ.setdefault("EMBED_MODEL", "nomic-embed-text")
os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", "2")
os.environ.setdefault("WEB_CONCURRENCY", "1")
os.environ.setdefault("NUM_CTX", "4096")
os.environ.setdefault("MAX_TOKENS_DEFAULT", "512")
os.environ.setdefault("MIN_FREE_DISK_GB", "0")
os.environ.setdefault("HARD_FREE_DISK_GB", "0")
os.environ.setdefault("ARTIFACT_DIR", "/tmp/cloudiator-test-artifacts")

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402


@pytest.fixture()
def settings():
    return get_settings()
