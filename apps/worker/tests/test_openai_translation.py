from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.config import get_settings, reset_settings
from app.errors import ApiError
from app.ollama_client import OllamaClient
from app.openai_compat import (
    build_ollama_chat_payload,
    openai_chat_response,
    openai_embeddings_response,
    openai_models_list,
    reject_unsupported,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDIATOR_ENV", "test")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "2")
    monkeypatch.setenv("DEFAULT_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    reset_settings()


def test_chat_translation_maps_ollama_fields() -> None:
    ollama = {
        "message": {"role": "assistant", "content": "hello"},
        "prompt_eval_count": 11,
        "eval_count": 4,
        "done": True,
    }
    out = openai_chat_response(ollama, model="qwen3.5:9b")
    assert out["object"] == "chat.completion"
    assert out["model"] == "qwen3.5:9b"
    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"]["prompt_tokens"] == 11
    assert out["usage"]["completion_tokens"] == 4
    assert out["usage"]["total_tokens"] == 15


def test_tool_calls_become_openai_tool_calls() -> None:
    ollama = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "geocode", "arguments": {"q": "Cairo"}}}],
        },
        "done": True,
        "eval_count": 8,
        "prompt_eval_count": 40,
    }
    out = openai_chat_response(ollama, model="qwen3.5:9b")
    assert out["choices"][0]["finish_reason"] == "tool_calls"
    call = out["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "geocode"
    assert json.loads(call["function"]["arguments"])["q"] == "Cairo"


def test_embeddings_translation() -> None:
    ollama = {"embeddings": [[0.1, 0.2, 0.3]]}
    out = openai_embeddings_response(ollama, model="nomic-embed-text", prompt_tokens=3)
    assert out["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert out["usage"]["prompt_tokens"] == 3


def test_legacy_single_embedding_vector() -> None:
    ollama = {"embedding": [0.5, 0.6]}
    out = openai_embeddings_response(ollama, model="nomic-embed-text", prompt_tokens=1)
    assert out["data"][0]["embedding"] == [0.5, 0.6]


def test_models_list_uses_live_tag_names_only() -> None:
    tags = [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]
    out = openai_models_list(tags)
    ids = [m["id"] for m in out["data"]]
    assert ids == ["qwen3.5:9b", "nomic-embed-text:latest"]
    assert "gpt-oss:20b" not in ids


def test_reject_n_greater_than_one() -> None:
    with pytest.raises(ApiError) as exc:
        reject_unsupported({"n": 3, "messages": []})
    assert exc.value.code == "not_supported"
    assert exc.value.param == "n"


@pytest.mark.parametrize(
    "key,value",
    [
        ("logprobs", True),
        ("top_logprobs", 2),
        ("best_of", 4),
        ("logit_bias", {"123": 1}),
    ],
)
def test_reject_unsupported_params(key: str, value: Any) -> None:
    with pytest.raises(ApiError) as exc:
        reject_unsupported({key: value, "messages": []})
    assert exc.value.code == "not_supported"
    assert exc.value.param == key


def test_n_equals_one_is_allowed() -> None:
    reject_unsupported({"n": 1, "messages": []})


def test_keep_alive_hot_vs_exclusive() -> None:
    settings = get_settings()
    client = OllamaClient(settings, client=httpx.AsyncClient(base_url="http://example.invalid"))
    assert client.keep_alive_for("qwen3.5:9b") == -1
    assert client.keep_alive_for("nomic-embed-text") == -1
    assert client.keep_alive_for("gpt-oss:20b") == 0


def test_ollama_payload_maps_openai_sampling() -> None:
    settings = get_settings()
    payload = build_ollama_chat_payload(
        {
            "model": "qwen3.5:9b",
            "max_tokens": 16,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        settings,
        [{"role": "user", "content": "hi"}],
    )
    assert payload["options"]["num_predict"] == 16
    assert payload["options"]["num_ctx"] == 4096
    assert payload["options"]["temperature"] == 0.2
    assert payload["format"] == "json"
