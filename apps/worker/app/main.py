"""Cloudiator worker — Phases A and B.

Bound to 127.0.0.1:8080, single process, one Metal slot. The OpenAI-compatible
surface here is chat, embeddings, and models; every route but `/v1/health` needs
an `sk-cld-` key. Neon holds the keys and the usage history, and neither is
allowed on the critical path of a chat: auth falls back to the 60s key cache and
usage falls back to the SQLite outbox. The tool loop is Phase D.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .admin import AccessVerifier, AdminGuard
from .auth import (
    Authenticator,
    KeyCache,
    KeyRecord,
    RateLimiter,
    clamp_max_tokens,
    effective_context,
    enforce_model_scope,
    require_capability,
)
from .config import get_settings
from .context_guard import enforce_context, estimate_prompt_tokens, prewarm_encoder
from .db import DatabaseUnavailable, Neon, pooled_endpoint
from .errors import CloudiatorError, mini_offline, model_not_found, not_supported
from .gates import BootRefused, run_boot_gates
from .logging_setup import configure_logging, scrub
from .ollama import OllamaClient, normalize_tag
from .openapi_filter import build_for_key, normalize_target
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
from .usage import UsageEvent, UsageOutbox

log = logging.getLogger("cloudiator.worker")

USAGE_EVENTS_LIMIT = 100
USAGE_ROLLUP_DAYS = 30

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
db = Neon(settings)
key_cache = KeyCache(settings.key_cache_ttl_seconds)
authenticator = Authenticator(settings, db, key_cache)
rate_limiter = RateLimiter()
outbox = UsageOutbox(settings, db)
access = AccessVerifier(settings)
admin_guard = AdminGuard(settings, access)


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
    _warn_about_phase_b_configuration()
    prewarm_encoder()
    outbox.open()
    await scheduler.poll_once()
    scheduler.start()
    outbox.start()
    warm = asyncio.create_task(_warm_models(), name="warm-models")
    try:
        yield
    finally:
        warm.cancel()
        await scheduler.stop()
        await outbox.stop()
        outbox.close()
        await ollama.aclose()
        await access.aclose()
        await db.close()


def _warn_about_phase_b_configuration() -> None:
    """Loud on the ways Phase B is configured wrong but still boots."""
    if not settings.database_url:
        log.warning(
            "DATABASE_URL is not set: no key can be looked up, so every request that is not "
            "already cached gets a 503. Put the pooled Neon URL in ~/Cloudiator/.env"
        )
    elif not pooled_endpoint(settings.database_url):
        log.warning(
            "DATABASE_URL is not the pooled Neon endpoint (no '-pooler' in the host). A "
            "long-lived process against a direct endpoint loses its connection on every "
            "idle suspend (PLAN.md §11)"
        )
    if not access.configured:
        log.warning(
            "CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD are not set: /v1/admin/* accepts nothing "
            "but the loopback break-glass token until they are (PLAN.md §12)"
        )


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
async def request_context_middleware(request: Request, call_next):
    """X-Request-Id on every response (PLAN.md §10) plus the usage row.

    The usage write is local and best effort: it goes to the SQLite outbox, never
    to Neon, and a failure here can never fail the request (PLAN.md §11).
    """
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.usage = UsageEvent(route=request.url.path, status=0, request_id=request_id)
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id

    event: UsageEvent = request.state.usage
    event.status = response.status_code
    event.latency_ms = int((time.monotonic() - started) * 1000)
    try:
        event.bytes_out = int(response.headers.get("content-length") or 0)
    except ValueError:
        event.bytes_out = None
    outbox.record(event)
    return response


def _error_response(request: Request, exc: CloudiatorError) -> JSONResponse:
    headers = exc.headers()
    headers["X-Request-Id"] = getattr(request.state, "request_id", str(uuid.uuid4()))
    event = getattr(request.state, "usage", None)
    if event is not None:
        event.error_code = exc.code
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


def require_key(*capabilities: str):
    """Authenticate, rate limit, then check scope — in that order.

    Scope is re-checked on every tool call later (PLAN.md §9); this is only the
    request-entry check. The 401/403/429 bodies are OpenAI-shaped because Apex
    parses them with JSON.deserialize.
    """

    async def dependency(request: Request) -> KeyRecord:
        record = await authenticator.authenticate(request.headers.get("authorization"))
        rate_limiter.check(record.key_id, record.rpm)
        for capability in capabilities:
            require_capability(record, capability)
        event = getattr(request.state, "usage", None)
        if event is not None:
            event.key_id = record.key_id
            event.tenant_id = record.tenant_id
        return record

    return dependency


async def require_admin(request: Request) -> str:
    return await admin_guard.identify(request)


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise CloudiatorError(400, "invalid_request_error", "Body must be JSON.") from exc
    if not isinstance(body, dict):
        raise CloudiatorError(400, "invalid_request_error", "Body must be a JSON object.")
    return body


async def _resolve_model(requested: Any, *, fallback: str, key: KeyRecord) -> str:
    model = requested or fallback
    if not isinstance(model, str):
        raise not_supported("model must be a string", param="model")
    # Scope first: a 403 for an out-of-scope model does not reveal what is on disk.
    enforce_model_scope(key, model, settings)
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
        # Last known Neon state. No round trip here: a suspended compute must not
        # page anyone about a healthy Mini (PLAN.md §10). /v1/health/deep does it.
        "db": db.state(),
        "outbox_depth": outbox.depth(),
        "degraded": snapshot["degraded"],
    }
    return JSONResponse(content=body)


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request, key: KeyRecord = Depends(require_key("chat"))
) -> JSONResponse:
    started = time.monotonic()
    body = await _json_body(request)
    validate_chat_params(body)

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise not_supported("messages must be a non-empty array", param="messages")

    model = await _resolve_model(body.get("model"), fallback=settings.default_model, key=key)
    request.state.usage.model = model

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

    # The key's own caps sit under the appliance-wide ones: a Salesforce key is
    # 512 tokens in a 4096 context whatever the request asked for.
    num_ctx = effective_context(key, resolve_num_ctx(settings))
    max_tokens = clamp_max_tokens(resolve_max_tokens(body, settings), key)
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
    usage = payload["usage"]
    request.state.usage.prompt_tokens = usage["prompt_tokens"]
    request.state.usage.completion_tokens = usage["completion_tokens"]
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
async def embeddings(
    request: Request, key: KeyRecord = Depends(require_key("embeddings"))
) -> JSONResponse:
    body = await _json_body(request)
    inputs = normalize_embeddings_input(body.get("input"))
    model = await _resolve_model(body.get("model"), fallback=settings.embed_model, key=key)
    request.state.usage.model = model

    # Slot 2 is the embedder. Embeddings never take metal_lock (PLAN.md §8 rule 2).
    vectors = await ollama.embeddings(model, inputs)
    prompt_tokens = estimate_prompt_tokens([{"role": "user", "content": text} for text in inputs])
    payload = embeddings_response_to_openai(vectors, model=model, prompt_tokens=prompt_tokens)
    request.state.usage.prompt_tokens = prompt_tokens
    return JSONResponse(content=payload)


@app.get("/v1/models")
async def models(key: KeyRecord = Depends(require_key())) -> JSONResponse:
    """Live `ollama tags` intersected with the key's scope (PLAN.md §10).

    Never from env: advertising a model that is not on disk means a caller can
    start a multi-gigabyte download inside an HTTP request.
    """
    try:
        tags = await ollama.tags()
    except CloudiatorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise mini_offline("Could not list models from Ollama.") from exc
    allowed = key.allowed_models(settings)
    scoped = [
        tag
        for tag in tags
        if normalize_tag(tag.get("name") or tag.get("model") or "") in allowed
    ]
    return JSONResponse(content=models_response_to_openai(scoped))


@app.get("/v1/openapi.json")
async def openapi_for_key(
    request: Request, key: KeyRecord = Depends(require_key())
) -> JSONResponse:
    """The contract for this key only (PLAN.md §10).

    `?target=salesforce` emits the restricted OpenAPI 3.0.3 subset External
    Services imports; the plain document is 3.1 for generic clients.
    """
    target = normalize_target(request.query_params.get("target"))
    document = build_for_key(
        sorted(key.capabilities),
        target=target,
        public_base_url=settings.public_base_url,
        version=__version__,
    )
    return JSONResponse(content=document)


@app.get("/v1/usage")
async def usage_rollup(key: KeyRecord = Depends(require_key())) -> JSONResponse:
    """Reads the daily rollup, not raw events (docs/schema.md retention)."""
    try:
        rollup = await db.fetch_usage_rollup(key.key_id, USAGE_ROLLUP_DAYS)
    except DatabaseUnavailable as exc:
        raise _usage_unavailable() from exc
    body = {"days": USAGE_ROLLUP_DAYS, "outbox_depth": outbox.depth(), **rollup}
    return JSONResponse(content=body)


@app.get("/v1/usage/events")
async def usage_events(key: KeyRecord = Depends(require_key())) -> JSONResponse:
    try:
        events = await db.fetch_usage_events(key.key_id, USAGE_EVENTS_LIMIT)
    except DatabaseUnavailable as exc:
        raise _usage_unavailable() from exc
    return JSONResponse(content={"data": events, "outbox_depth": outbox.depth()})


def _usage_unavailable() -> CloudiatorError:
    return mini_offline(
        "Usage history lives in Neon and Neon is unreachable right now. Inference is "
        "unaffected; rows are queued locally and flush when it returns."
    )


@app.post("/v1/admin/cache/flush")
async def admin_flush_cache(identity: str = Depends(require_admin)) -> JSONResponse:
    """Make a revocation immediate instead of waiting out the 60s cache."""
    flushed = key_cache.flush()
    log.info("key cache flushed by %s (%d entries)", identity, flushed)
    return JSONResponse(content={"flushed": flushed, "ttl_seconds": key_cache.ttl})


@app.get("/v1/health/deep")
async def health_deep(identity: str = Depends(require_admin)) -> JSONResponse:
    """The round trips /v1/health refuses to make (PLAN.md §10)."""
    snapshot = scheduler.snapshot()
    neon: dict[str, Any] = {"state": db.state(), "configured": db.configured}
    if db.configured:
        try:
            neon["ping_ms"] = round(await db.ping(), 1)
        except DatabaseUnavailable as exc:
            # A connection error can carry the whole DSN, and this body ends up
            # pasted into tickets.
            neon["error"] = scrub(str(exc))
    neon["pooled_endpoint"] = pooled_endpoint(settings.database_url)

    models_on_disk: Any
    try:
        models_on_disk = sorted(await ollama.installed_tags())
    except Exception as exc:  # noqa: BLE001 - deep health reports, never raises
        models_on_disk = {"error": str(exc)}

    return JSONResponse(
        content={
            "identity": identity,
            "version": __version__,
            "neon": neon,
            "outbox": {
                "depth": outbox.depth(),
                "dropped": outbox.dropped(),
                "flushed": outbox.flushed,
                "path": outbox.path,
            },
            "key_cache": key_cache.stats(),
            "models_on_disk": models_on_disk,
            "scheduler": snapshot,
        }
    )


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
