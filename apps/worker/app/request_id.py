"""X-Request-Id on every response, including errors (PLAN.md §10)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound = request.headers.get("x-request-id") or request.headers.get("X-Request-Id")
        request_id = inbound.strip() if inbound and inbound.strip() else str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            # Exception handlers still need the id; re-raise after stashing.
            raise
        response.headers["X-Request-Id"] = request_id
        return response
