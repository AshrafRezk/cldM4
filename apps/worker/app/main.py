"""Cloudiator worker — Phase A.

Bound to 127.0.0.1:8080, single process, one Metal slot. The OpenAI-compatible
surface here is chat, embeddings, and models; auth, Neon, and the tunnel are
Phase B, and the tool loop is Phase D.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .context_guard import enforce_context, estimate_prompt_tokens, prewarm_encoder
from .errors import CloudiatorError, mini_offline, model_not_found, not_supported
from .gates import BootRefused, run_boot_gates
from .logging_setup import configure_logging
from .ollama import OllamaClient, normalize_tag
from .scheduler import Scheduler
from .ssrf import prepare_messages_for_ollama, validate_image_inputs
from .translation import (
    build_options,
    chat_response_to_openai,
    embeddings_response_to_openai,
    models_response_to_openai,
    normalize_embeddings_input,
    resolve_max_tokens,
    resolve_num_ctx,
    validate_chat_params,
)

log = logging.getLogger("cloudiator.worker")

# Endpoint families that will never exist in v1. A 404 with an OpenAI-shaped
# body makes SDKs surface a readable error instead of an HTML page (PLAN.md §10).
UNSUPPORTED_PATHS = (
    "/v1/assistants",
    "/v1/threads",
    "/v1/fine_tuning",
    "/v1/files",
    "/v1/images/edits",
    "/v1/images/variations",
    "/v1/moderations",
    "/v1/batches",
)

settings = get_settings()
ollama = OllamaClient(
    settings.ollama_host,
    default_model=settings.default_model,
    embed_model=settings.embed_model,
    chat_timeout=float(settings.sync_deadline_seconds),
    embeddings_timeout=float(settings.embeddings_timeout_seconds),
)
scheduler = Scheduler(settings, ollama)


class HealthLimiter:
    """Health is unauthenticated, so it gets its own small bucket (PLAN.md §10)."""

    def __init__(self, rpm: int) -> None:
        self.capacity = max(1, rpm)
        self.tokens = float(self.capacity)
        self.refill_per_second = self.capacity / 60.0
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(
            float(self.capacity), self.tokens + (now - self.updated) * self.refill_per_second
        )
        self.updated = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


health_limiter = HealthLimiter(settings.health_rpm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        await run_boot_gates(settings)
    except BootRefused as exc:
        log.error("refusing to boot: %s", exc)
        raise
    log.info(
        "cloudiator worker %s starting: model=%s embedder=%s num_ctx=%s",
        __version__,
        settings.default_model,
        settings.embed_model,
        resolve_num_ctx(settings),
    )
    prewarm_encoder()
    await scheduler.poll_once()
    scheduler.start()
    warm = asyncio.create_task(_warm_models(), name="warm-models")
    try:
        yield
    finally:
        warm.cancel()
        await scheduler.stop()
        await ollama.aclose()


async def _warm_models() -> None:
    """Best effort: a cold first call spends 5-15s of the caller's budget."""
    for action, label in ((ollama.reload_hot_model, "hot model"), (ollama.warm_embedder, "embedder")):
        try:
            await action()
            log.info("warmed %s", label)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("could not warm %s: %s", label, exc)


app = FastAPI(
    title="Cloudiator worker",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """X-Request-Id on every response, including errors (PLAN.md §10)."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


def _error_response(request: Request, exc: CloudiatorError) -> JSONResponse:
    headers = exc.headers()
    headers["X-Request-Id"] = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=headers)


@app.exception_handler(CloudiatorError)
async def cloudiator_error_handler(request: Request, exc: CloudiatorError) -> JSONResponse:
    return _error_response(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        request,
        CloudiatorError(400, "invalid_request_error", "The request body is not valid JSON."),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return _error_response(
        request,
        CloudiatorError(
            500,
            "internal_error",
            "The appliance failed to handle this request.",
            error_type="server_error",
        ),
    )


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "Body must be JSON.") from exc
    if not isinstance(body, dict):
        raise CloudiatorError(400, "invalid_request_error", "Body must be a JSON object.")
    return body


async def _resolve_model(requested: Any, *, fallback: str) -> str:
    model = requested or fallback
    if not isinstance(model, str):
        raise not_supported("model must be a string", param="model")
    try:
        installed = await ollama.installed_tags()
    except CloudiatorError:
        # Ollama unreachable: let the call itself produce mini_offline.
        return model
    if normalize_tag(model) not in installed:
        raise model_not_found(model)
    return model


@app.get("/v1/health")
async def health(request: Request) -> JSONResponse:
    if not health_limiter.allow():
        raise CloudiatorError(
            429,
            "insufficient_quota",
            "Health is rate limited.",
            error_type="rate_limit_error",
            retry_after=1,
        )
    snapshot = scheduler.snapshot()
    body = {
        "ok": not snapshot["degraded"],
        "version": __version__,
        "state": snapshot["state"],
        "free_mb": snapshot["free_mb"],
        "loaded": snapshot["loaded"],
        "queue_depth": snapshot["queue_depth"],
        "pressure": snapshot["pressure"],
        "swap_used_mb": snapshot["swap_used_mb"],
        "free_disk_gb": snapshot["free_disk_gb"],
        # Phase B replaces this with the real Neon state and an outbox depth.
        "db": "not_configured",
        "outbox_depth": 0,
        "degraded": snapshot["degraded"],
    }
    return JSONResponse(content=body)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    started = time.monotonic()
    body = await _json_body(request)
    validate_chat_params(body)

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise not_supported("messages must be a non-empty array", param="messages")

    model = await _resolve_model(body.get("model"), fallback=settings.default_model)

    image_urls = validate_image_inputs(messages, settings=settings)
    if image_urls and not (settings.vision_model or settings.default_model_has_vision):
        raise CloudiatorError(
            404,
            "model_not_found",
            f"{model} does not accept image inputs on this appliance. Extract text from images "
            "with the OCR tools instead.",
            param="model",
        )
    prepared = await prepare_messages_for_ollama(messages, settings=settings)

    num_ctx = resolve_num_ctx(settings)
    max_tokens = resolve_max_tokens(body, settings)
    prompt_tokens = estimate_prompt_tokens(prepared, body.get("tools"))
    enforce_context(prompt_tokens, max_tokens, num_ctx)

    options = build_options(body, num_ctx=num_ctx, max_tokens=max_tokens)
    response_format = (body.get("response_format") or {}).get("type")

    async with scheduler.chat_slot():
        remaining = settings.sync_deadline_seconds - (time.monotonic() - started)
        if remaining <= 1:
            raise _deadline_error()
        try:
            raw = await asyncio.wait_for(
                ollama.chat(
                    model,
                    prepared,
                    options=options,
                    tools=body.get("tools"),
                    response_format=response_format,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            raise _deadline_error() from None

    payload = chat_response_to_openai(raw, model=model, estimated_prompt_tokens=prompt_tokens)
    return JSONResponse(content=payload)


def _deadline_error() -> CloudiatorError:
    return CloudiatorError(
        504,
        "request_timeout",
        f"The appliance did not finish within {settings.sync_deadline_seconds}s. Cloudflare "
        "returns an HTML 524 past ~100s, so the worker fails first. Use POST /v1/jobs for long "
        "work.",
        error_type="server_error",
        param="POST /v1/jobs",
    )


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    body = await _json_body(request)
    inputs = normalize_embeddings_input(body.get("input"))
    model = await _resolve_model(body.get("model"), fallback=settings.embed_model)

    # Slot 2 is the embedder. Embeddings never take metal_lock (PLAN.md §8 rule 2).
    vectors = await ollama.embeddings(model, inputs)
    prompt_tokens = estimate_prompt_tokens([{"role": "user", "content": text} for text in inputs])
    payload = embeddings_response_to_openai(vectors, model=model, prompt_tokens=prompt_tokens)
    return JSONResponse(content=payload)


@app.get("/v1/models")
async def models() -> JSONResponse:
    """Built from live `ollama tags`, never from env (PLAN.md §7)."""
    try:
        tags = await ollama.tags()
    except CloudiatorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise mini_offline("Could not list models from Ollama.") from exc
    return JSONResponse(content=models_response_to_openai(tags))


def _unsupported_error(path: str) -> CloudiatorError:
    return not_supported(
        f"{path} is not part of this appliance's API. GET /v1/models lists what exists.",
        param=path,
        status_code=404,
    )


def _register_unsupported_paths(application: FastAPI) -> None:
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    for path in UNSUPPORTED_PATHS:

        def make_exact(family: str):
            async def handler() -> JSONResponse:
                raise _unsupported_error(family)

            return handler

        def make_wildcard(family: str):
            async def handler(rest: str) -> JSONResponse:
                raise _unsupported_error(family)

            return handler

        application.add_api_route(
            path, make_exact(path), methods=methods, include_in_schema=False
        )
        application.add_api_route(
            path + "/{rest:path}",
            make_wildcard(path),
            methods=methods,
            include_in_schema=False,
        )


_register_unsupported_paths(app)
