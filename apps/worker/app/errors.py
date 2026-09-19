"""OpenAI-shaped errors (PLAN.md §10).

Every failure the caller can see is one of these. Salesforce Apex parses the
body with JSON.deserialize, so an HTML error page from any layer is a bug.
"""

from __future__ import annotations

from typing import Any


class CloudiatorError(Exception):
    """An error with an OpenAI-shaped body and a known HTTP status."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        error_type: str = "invalid_request_error",
        param: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type
        self.param = param
        self.retry_after = retry_after

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }

    def headers(self) -> dict[str, str]:
        if self.retry_after is None:
            return {}
        return {"Retry-After": str(self.retry_after)}


def not_supported(message: str, *, param: str | None = None, status_code: int = 400) -> CloudiatorError:
    return CloudiatorError(status_code, "not_supported", message, param=param)


def context_length_exceeded(message: str) -> CloudiatorError:
    return CloudiatorError(400, "context_length_exceeded", message, param="messages")


def url_not_allowed(message: str) -> CloudiatorError:
    return CloudiatorError(400, "url_not_allowed", message, param="image_url")


def model_not_found(model: str) -> CloudiatorError:
    return CloudiatorError(
        404,
        "model_not_found",
        f"Model {model!r} is not loaded on this appliance. GET /v1/models lists what is on disk.",
        param="model",
    )


def metal_busy() -> CloudiatorError:
    return CloudiatorError(
        429,
        "metal_busy",
        "The Metal slot is busy. Retry shortly, or submit the request to POST /v1/jobs.",
        error_type="rate_limit_error",
        param="POST /v1/jobs",
        retry_after=5,
    )


def mini_offline(message: str) -> CloudiatorError:
    return CloudiatorError(503, "mini_offline", message, error_type="server_error")


def disk_full(free_gb: float, floor_gb: float) -> CloudiatorError:
    return CloudiatorError(
        429,
        "disk_full",
        f"Only {free_gb:.1f} GB free on the appliance disk; {floor_gb:.1f} GB is the floor "
        "for work that writes. Generation is refused until space is reclaimed.",
        error_type="rate_limit_error",
        retry_after=300,
    )


def upload_too_large(limit_bytes: int) -> CloudiatorError:
    return CloudiatorError(413, "upload_too_large", f"Upload exceeds {limit_bytes} bytes.")
