"""OpenAI-shaped errors (PLAN.md §10)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        type_: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.type = type_
        self.code = code
        self.param = param

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.type,
                "param": self.param,
                "code": self.code,
            }
        }


def invalid_api_key(message: str = "Invalid API key") -> ApiError:
    return ApiError(401, message, type_="invalid_request_error", code="invalid_api_key")


def scope_denied(message: str, param: str | None = None) -> ApiError:
    return ApiError(403, message, type_="invalid_request_error", code="scope_denied", param=param)


def model_not_found(model: str) -> ApiError:
    return ApiError(
        404,
        f"The model `{model}` does not exist or is not available on this appliance.",
        type_="invalid_request_error",
        code="model_not_found",
        param="model",
    )


def not_supported(message: str, param: str | None = None, status_code: int = 400) -> ApiError:
    return ApiError(
        status_code,
        message,
        type_="invalid_request_error",
        code="not_supported",
        param=param,
    )


def context_length_exceeded(prompt_tokens: int, max_tokens: int, max_context: int) -> ApiError:
    return ApiError(
        400,
        (
            f"This request would use {prompt_tokens} prompt tokens plus {max_tokens} "
            f"completion tokens, which exceeds max_context={max_context}. "
            "Shorten the prompt or lower max_tokens. Ollama would otherwise silently "
            "drop the oldest tokens."
        ),
        type_="invalid_request_error",
        code="context_length_exceeded",
        param="messages",
    )


def url_not_allowed(message: str, param: str = "image_url") -> ApiError:
    return ApiError(400, message, type_="invalid_request_error", code="url_not_allowed", param=param)


def metal_busy() -> ApiError:
    return ApiError(
        429,
        "The Mini's Metal slot is busy. Retry after a few seconds, or use POST /v1/jobs.",
        type_="invalid_request_error",
        code="metal_busy",
        param="POST /v1/jobs",
    )


def mini_offline(message: str = "Ollama is not reachable on 127.0.0.1:11434") -> ApiError:
    return ApiError(503, message, type_="api_error", code="mini_offline")


def disk_full(free_gb: float) -> ApiError:
    return ApiError(
        429,
        f"Disk is too full ({free_gb:.1f} GB free). Free space or wait for the artifact janitor.",
        type_="invalid_request_error",
        code="disk_full",
    )


def upload_too_large(message: str) -> ApiError:
    return ApiError(413, message, type_="invalid_request_error", code="upload_too_large")


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"X-Request-Id": request_id} if request_id else {}
    if exc.status_code == 429:
        headers["Retry-After"] = "5"
    return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"X-Request-Id": request_id} if request_id else {}
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": first.get("msg", "Invalid request"),
                "type": "invalid_request_error",
                "param": loc or None,
                "code": "invalid_request_error",
            }
        },
        headers=headers,
    )
