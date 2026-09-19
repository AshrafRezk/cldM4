from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.runtime import assert_web_concurrency


def test_web_concurrency_must_be_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(SystemExit, match="WEB_CONCURRENCY"):
        assert_web_concurrency()


@respx.mock
def test_health_json_has_no_secrets_and_request_id() -> None:
    respx.get("http://127.0.0.1:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})
    )
    with TestClient(app) as client:
        response = client.get("/v1/health", headers={"X-Request-Id": "test-rid-1"})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "test-rid-1"
    body = response.json()
    for key in (
        "ok",
        "free_mb",
        "loaded",
        "queue_depth",
        "outbox_depth",
        "pressure",
        "free_disk_gb",
        "db",
        "version",
    ):
        assert key in body
    blob = json.dumps(body).lower()
    for secret in ("sk-cld", "password", "argon2", "neon.tech", "database_url", "authorization"):
        assert secret not in blob
    assert body["db"] == "skipped"
    assert body["loaded"] == ["qwen3.5:9b"]


@respx.mock
def test_chat_sends_explicit_keep_alive_and_think_false() -> None:
    chat = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "hi"},
                "prompt_eval_count": 5,
                "eval_count": 1,
                "done": True,
            },
        )
    )
    respx.get("http://127.0.0.1:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:9b",
                "messages": [{"role": "user", "content": "say hi"}],
                "max_tokens": 16,
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers.get("x-request-id")
    payload = json.loads(chat.calls[0].request.content)
    assert payload["keep_alive"] == -1
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 16
    assert payload["options"]["num_ctx"] == 4096
    assert response.json()["choices"][0]["message"]["content"] == "hi"


@respx.mock
def test_embeddings_keep_alive_and_nomic_prefix() -> None:
    embed = respx.post("http://127.0.0.1:11434/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})
    )
    respx.get("http://127.0.0.1:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": "nomic-embed-text", "input": "hello world"},
        )
    assert response.status_code == 200, response.text
    payload = json.loads(embed.calls[0].request.content)
    assert payload["keep_alive"] == -1
    assert payload["input"] == "search_query: hello world"


@respx.mock
def test_models_from_live_tags_not_env() -> None:
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]},
        )
    )
    respx.get("http://127.0.0.1:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    with TestClient(app) as client:
        response = client.get("/v1/models")
    ids = [m["id"] for m in response.json()["data"]]
    assert ids == ["qwen3.5:9b", "nomic-embed-text:latest"]
    assert "gpt-oss:20b" not in ids


def test_unsupported_openai_families_are_404() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/assistants")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_supported"
    assert response.headers.get("x-request-id")


def test_error_responses_include_request_id() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "qwen3.5:9b", "n": 3, "messages": [{"role": "user", "content": "x"}]},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_supported"
    assert response.headers.get("x-request-id")
