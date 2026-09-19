"""Shared pytest env so importing app.main never trips production boot gates."""

from __future__ import annotations

import os

os.environ.setdefault("CLOUDIATOR_ENV", "test")
os.environ.setdefault("WEB_CONCURRENCY", "1")
os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", "2")
os.environ.setdefault("DEFAULT_MODEL", "qwen3.5:9b")
os.environ.setdefault("EMBED_MODEL", "nomic-embed-text")
os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:11434")
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8080")
