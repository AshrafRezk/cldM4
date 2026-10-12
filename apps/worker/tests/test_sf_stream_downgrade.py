"""Salesforce keys accept stream:true and return JSON + downgrade header (Phase F)."""

from __future__ import annotations

import pytest

from app.translation import resolve_stream_downgrade
from app.errors import CloudiatorError


def test_force_no_stream_downgrades_stream_true():
    assert resolve_stream_downgrade({"stream": True}, force_no_stream=True) is True


def test_force_no_stream_leaves_stream_false_alone():
    assert resolve_stream_downgrade({"stream": False}, force_no_stream=True) is False
    assert resolve_stream_downgrade({}, force_no_stream=True) is False


def test_browser_key_still_rejects_stream():
    with pytest.raises(CloudiatorError) as exc:
        resolve_stream_downgrade({"stream": True}, force_no_stream=False)
    assert exc.value.status_code == 400
    assert exc.value.param == "stream"


async def test_http_salesforce_key_downgrades_stream(make_client, install_key, monkeypatch):
    from app import main

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "hi from gemma"},
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 3,
        }

    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    monkeypatch.setattr(main.ollama, "chat", chat)
    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)

    _record, headers = install_key(force_no_stream=True, capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
                "max_tokens": 16,
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers.get("x-cloudiator-stream-downgraded") == "true"
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hi from gemma"


async def test_http_non_salesforce_key_still_400_on_stream(make_client, install_key):
    _record, headers = install_key(force_no_stream=False, capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "stream"
