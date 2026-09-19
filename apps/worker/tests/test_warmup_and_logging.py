from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import get_settings, reset_settings
from app.logging_setup import RedactFilter, configure_logging
from app.main import _warmup_safe, app
from app.ollama_client import OllamaClient


def test_redact_filter_formats_httpx_percent_d() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname="client.py",
        lineno=1740,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=("POST", "http://127.0.0.1:11434/api/generate", "HTTP/1.1", 200, "OK"),
        exc_info=None,
    )
    assert RedactFilter().filter(record) is True
    assert record.args == ()
    assert 'HTTP Request: POST http://127.0.0.1:11434/api/generate "HTTP/1.1 200 OK"' == record.getMessage()


def test_redact_filter_strips_keys_after_format() -> None:
    record = logging.LogRecord(
        name="cloudiator",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="auth %s",
        args=("Authorization: Bearer sk-cld-abc_secret",),
        exc_info=None,
    )
    RedactFilter().filter(record)
    rendered = record.getMessage()
    assert "sk-cld-abc_secret" not in rendered
    assert "sk-cld-[REDACTED]" in rendered or "[REDACTED]" in rendered


def test_configure_logging_does_not_raise_on_httpx_info(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging()
    httpx_log = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        httpx_log.info(
            'HTTP Request: %s %s "%s %d %s"',
            "POST",
            "http://127.0.0.1:11434/api/generate",
            "HTTP/1.1",
            200,
            "OK",
        )
    assert "200" in caplog.text


@pytest.mark.asyncio
async def test_warmup_sends_stream_false_and_think_false() -> None:
    reset_settings()
    settings = get_settings()
    with respx.mock(base_url=settings.ollama_host) as router:
        generate = router.post("/api/generate").mock(return_value=httpx.Response(200, json={"done": True}))
        router.post("/api/embed").mock(return_value=httpx.Response(200, json={"embeddings": [[0.1]]}))
        client = OllamaClient(settings)
        await client.warmup()
        await client.aclose()
    payload = json.loads(generate.calls[0].request.content)
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == -1
    assert payload["options"]["num_predict"] == 0


@pytest.mark.asyncio
async def test_warmup_safe_does_not_raise() -> None:
    class Boom:
        async def warmup(self) -> None:
            raise RuntimeError("ollama exploded")

    class Settings:
        cloudiator_env = "production"

    await _warmup_safe(Boom(), Settings())  # type: ignore[arg-type]


@respx.mock
def test_health_up_while_warmup_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDIATOR_FORCE_WARMUP", "1")

    async def hang(self: OllamaClient) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(OllamaClient, "warmup", hang)
    respx.get("http://127.0.0.1:11434/api/ps").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    with TestClient(app) as client:
        response = client.get("/v1/health")
    assert response.status_code == 200
    assert "ok" in response.json()
