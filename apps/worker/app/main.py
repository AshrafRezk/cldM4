"""FastAPI worker. Binds 127.0.0.1:8080, uvicorn --workers 1."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app import __version__
from app.config import Settings, get_settings
from app.context_guard import assert_context_fits, encode_len
from app.errors import (
    ApiError,
    api_error_handler,
    mini_offline,
    not_supported,
    validation_error_handler,
)
from app.logging_setup import configure_logging, headers_for_log
from app.memory import monitor
from app.ollama_client import OllamaClient, generative_names
from app.openai_compat import (
    build_ollama_chat_payload,
    openai_chat_response,
    openai_embeddings_response,
    openai_messages_to_ollama,
    openai_models_list,
    openai_stream_chunk,
    reject_unsupported,
)
from app.request_id import RequestIdMiddleware
from app.runtime import assert_runtime, release_pidfile
from app.scheduler import scheduler

log = logging.getLogger("cloudiator")

UNSUPPORTED_PREFIXES = (
    "/v1/assistants",
    "/v1/threads",
    "/v1/fine_tuning",
    "/v1/files",
    "/v1/moderations",
    "/v1/batches",
    "/v1/images/edits",
    "/v1/images/variations",
)

_health_hits: dict[str, deque[float]] = defaultdict(deque)


async def _warmup_safe(ollama: OllamaClient, settings: Settings) -> None:
    """Background pin of 9B + embedder. Failures must not take down :8080."""
    force = os.environ.get("CLOUDIATOR_FORCE_WARMUP", "").lower() in {"1", "true", "yes"}
    if settings.cloudiator_env.lower() == "test" and not force:
        return
    try:
        await ollama.warmup()
        log.info("ollama warmup complete")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("ollama warmup failed; worker stays up on 127.0.0.1:8080")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    assert_runtime(settings)
    ollama = OllamaClient(settings)
    app.state.settings = settings
    app.state.ollama = ollama
    await monitor.start(settings)
    warmup_task = asyncio.create_task(_warmup_safe(ollama, settings), name="ollama-warmup")
    app.state.warmup_task = warmup_task
    log.info("worker ready version=%s host=%s port=%s", __version__, settings.host, settings.port)
    try:
        yield
    finally:
        warmup_task.cancel()
        try:
            await warmup_task
        except asyncio.CancelledError:
            pass
        await monitor.stop()
        await ollama.aclose()
        release_pidfile(settings)


def create_app() -> FastAPI:
    application = FastAPI(
        title="Cloudiator",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)

    @application.middleware("http")
    async def strip_auth_from_logs(request: Request, call_next):
        log.debug("request %s %s headers=%s", request.method, request.url.path, headers_for_log(request.headers))
        return await call_next(request)

    @application.get("/v1/health")
    async def health(request: Request) -> dict[str, Any]:
        _rate_limit_health(request, get_settings())
        settings: Settings = request.app.state.settings
        ollama: OllamaClient = request.app.state.ollama
        snap = monitor.snapshot
        loaded = await ollama.loaded_names()
        gens = generative_names(loaded, settings.embed_model)
        degraded = False
        if len(gens) > 1:
            log.error("P0: two generative models loaded: %s", gens)
            degraded = True
        if snap.pressure != "normal":
            degraded = True
        if snap.free_disk_gb < settings.min_free_disk_gb:
            degraded = True
        ok = not degraded
        return {
            "ok": ok,
            "free_mb": snap.free_mb,
            "loaded": loaded,
            "queue_depth": 0,
            "outbox_depth": 0,
            "pressure": snap.pressure,
            "free_disk_gb": snap.free_disk_gb,
            "db": "skipped",
            "version": __version__,
        }

    @application.get("/v1/models")
    async def list_models(request: Request) -> dict[str, Any]:
        ollama: OllamaClient = request.app.state.ollama
        tags = await ollama.tags()
        return openai_models_list(tags)

    @application.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        settings: Settings = request.app.state.settings
        ollama: OllamaClient = request.app.state.ollama
        body = await _json_body(request)
        reject_unsupported(body)
        model = str(body.get("model") or settings.default_model)
        messages = list(body.get("messages") or [])
        if not messages:
            raise not_supported("messages is required", param="messages")
        max_tokens = int(body.get("max_tokens") or settings.max_tokens_default)
        prompt_tokens = assert_context_fits(messages, max_tokens, settings)
        vision_ok = settings.default_model_vision and model == settings.default_model
        ollama_messages = await openai_messages_to_ollama(
            messages, settings, vision_supported=vision_ok
        )
        payload = build_ollama_chat_payload(body, settings, ollama_messages)
        stream = bool(body.get("stream"))
        if stream:
            return StreamingResponse(
                _stream_chat(ollama, payload, model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        async with scheduler.acquire_metal():
            result = await ollama.chat(payload, stream=False)
        return openai_chat_response(result, model=model, prompt_tokens=prompt_tokens)

    @application.post("/v1/embeddings")
    async def embeddings(request: Request) -> dict[str, Any]:
        settings: Settings = request.app.state.settings
        ollama: OllamaClient = request.app.state.ollama
        body = await _json_body(request)
        model = str(body.get("model") or settings.embed_model)
        raw_input = body.get("input")
        if raw_input is None:
            raise not_supported("input is required", param="input")
        inputs = raw_input if isinstance(raw_input, list) else [raw_input]
        texts = [str(x) for x in inputs]
        prompt_tokens = sum(encode_len(t) for t in texts)
        result = await ollama.embed(model, texts)
        return openai_embeddings_response(result, model=model, prompt_tokens=prompt_tokens)

    @application.api_route("/v1/images/generations", methods=["GET", "POST"])
    async def images_generations() -> None:
        raise not_supported(
            "Image generation is Phase E (FLUX jobs). Use POST /v1/jobs after that phase.",
            status_code=404,
        )

    @application.api_route("/v1/audio/transcriptions", methods=["GET", "POST"])
    async def transcriptions() -> None:
        raise not_supported("Audio transcriptions are Phase F.", status_code=404)

    @application.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def not_implemented(path: str) -> None:
        routed = "/" + path
        if routed.startswith("/v1/") and any(
            routed == p or routed.startswith(p + "/") for p in UNSUPPORTED_PREFIXES
        ):
            raise not_supported(f"{routed} is not supported in Cloudiator v1", status_code=404)
        raise not_supported(f"{routed} is not implemented in Phase A", status_code=404)

    return application


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise not_supported("Request body must be JSON") from exc
    if not isinstance(body, dict):
        raise not_supported("Request body must be a JSON object")
    return body


async def _stream_chat(ollama: OllamaClient, payload: dict[str, Any], model: str) -> AsyncIterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    async with scheduler.acquire_metal():
        async for part in ollama.chat_stream(payload):
            chunk = openai_stream_chunk(part, model=model, chunk_id=chunk_id)
            yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


def _rate_limit_health(request: Request, settings: Settings) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = 60.0
    bucket = _health_hits[ip]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= settings.health_rpm:
        raise ApiError(
            429,
            "Health endpoint rate limit",
            type_="invalid_request_error",
            code="rate_limited",
        )
    bucket.append(now)


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    if settings.host != "127.0.0.1":
        raise SystemExit("refuse to bind anything but 127.0.0.1")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.port,
        workers=1,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
