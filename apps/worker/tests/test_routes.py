"""HTTP surface.

Exercised through ASGI without the lifespan: the boot gates refuse to run
anywhere but arm64 macOS, and they are proven on the Mini by
scripts/smoke-phase-a.sh rather than mocked out here.
"""

from __future__ import annotations

import httpx
import pytest

from app import main


@pytest.fixture()
def client():
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080")


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch):
    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    async def tags():
        return [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 8,
            "eval_count": 2,
        }

    async def embeddings(model, inputs):
        return [[0.1, 0.2, 0.3] for _ in inputs]

    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)
    monkeypatch.setattr(main.ollama, "tags", tags)
    monkeypatch.setattr(main.ollama, "chat", chat)
    monkeypatch.setattr(main.ollama, "embeddings", embeddings)


async def test_health_reports_the_documented_fields(client):
    async with client:
        response = await client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    for field in (
        "ok",
        "free_mb",
        "loaded",
        "queue_depth",
        "pressure",
        "free_disk_gb",
        "db",
        "version",
    ):
        assert field in body, f"/v1/health must report {field}"
    assert body["ok"] is True
    assert body["db"] == "not_configured"


async def test_health_leaks_no_secrets(client):
    async with client:
        body = (await client.get("/v1/health")).text

    for forbidden in ("sk-cld", "postgres", "Bearer", "secret", "/Users/"):
        assert forbidden not in body


async def test_every_response_carries_a_request_id(client):
    async with client:
        response = await client.get("/v1/health")
    assert response.headers["x-request-id"]


async def test_an_inbound_request_id_is_preserved(client):
    async with client:
        response = await client.get("/v1/health", headers={"X-Request-Id": "req-from-cloudflare"})
    assert response.headers["x-request-id"] == "req-from-cloudflare"


async def test_errors_also_carry_a_request_id(client):
    async with client:
        response = await client.post("/v1/chat/completions", json={"messages": [], "n": 4})

    assert response.status_code == 400
    assert response.headers["x-request-id"]
    assert response.json()["error"]["code"] == "not_supported"


async def test_chat_returns_an_openai_completion(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:9b",
                "messages": [{"role": "user", "content": "say hi"}],
                "max_tokens": 16,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hi"


async def test_chat_defaults_to_the_configured_model(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
        )
    assert response.json()["model"] == "qwen3.5:9b"


async def test_a_model_that_is_not_on_disk_is_a_404(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-oss:20b", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


async def test_an_image_without_a_vision_model_is_a_404(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "read this"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/a.png"},
                            },
                        ],
                    }
                ]
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


async def test_an_oversized_prompt_is_rejected_before_ollama_truncates_it(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "word " * 20000}],
                "max_tokens": 512,
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"


async def test_streaming_is_refused_loudly(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "stream"


async def test_embeddings_returns_a_vector_per_input(client):
    async with client:
        response = await client.post(
            "/v1/embeddings", json={"model": "nomic-embed-text", "input": ["a", "b"]}
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]


async def test_models_are_listed_from_live_tags(client):
    async with client:
        response = await client.get("/v1/models")

    assert [item["id"] for item in response.json()["data"]] == [
        "qwen3.5:9b",
        "nomic-embed-text:latest",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/assistants",
        "/v1/threads",
        "/v1/fine_tuning/jobs",
        "/v1/files",
        "/v1/images/edits",
        "/v1/images/variations",
        "/v1/moderations",
        "/v1/batches",
    ],
)
async def test_endpoint_families_that_will_never_exist_return_openai_shaped_404s(client, path):
    async with client:
        response = await client.post(path, json={})

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_supported"
    assert set(body["error"]) == {"message", "type", "param", "code"}


async def test_a_non_json_body_is_an_openai_error(client):
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert "error" in response.json()
