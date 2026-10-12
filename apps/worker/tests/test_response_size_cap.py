"""max_response_bytes on force_no_stream keys → artifact + truncated preview (Phase F)."""

from __future__ import annotations

import json

import pytest

from app.translation import enforce_max_response_bytes


class FakeArtifacts:
    def __init__(self) -> None:
        self.saved: list[tuple[bytes, str]] = []

    def save(self, data: bytes, suffix: str) -> str:
        self.saved.append((data, suffix))
        return "deadbeef" + "0" * 24

    def sign(self, artifact_id: str) -> str:
        return f"https://api.cloudiator.test/artifacts/{artifact_id}?sig=test"


def _payload(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen3.5:9b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_small_payload_passes_through():
    artifacts = FakeArtifacts()
    payload = _payload("short")
    out = enforce_max_response_bytes(payload, max_bytes=1_048_576, artifacts=artifacts)
    assert out is payload or out == payload
    assert "artifact" not in out
    assert artifacts.saved == []


def test_oversized_payload_becomes_artifact_preview():
    artifacts = FakeArtifacts()
    huge = "كلمة " * 50_000  # Arabic + spaces — well over 1 KB
    payload = _payload(huge)
    out = enforce_max_response_bytes(payload, max_bytes=2048, artifacts=artifacts)
    assert out["artifact"]["truncated"] is True
    assert out["artifact"]["id"].startswith("deadbeef")
    assert out["artifact"]["url"].startswith("https://api.cloudiator.test/")
    assert artifacts.saved and artifacts.saved[0][1] == ".json"
    encoded = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= 2048
    assert "truncated" in out["choices"][0]["message"]["content"]
    assert out["choices"][0]["finish_reason"] == "length"


async def test_http_oversized_chat_returns_artifact(make_client, install_key, monkeypatch):
    from app import main

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "X" * 20_000},
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 100,
        }

    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    monkeypatch.setattr(main.ollama, "chat", chat)
    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)

    _record, headers = install_key(
        force_no_stream=True,
        max_response_bytes=1500,
        capabilities=["chat"],
    )
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "write a lot"}],
                "max_tokens": 512,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact"]["truncated"] is True
    assert "id" in body["artifact"]
    assert len(response.content) <= 1500 + 200  # header overhead allowance via body size
    assert len(json.dumps(body).encode("utf-8")) <= 1500
