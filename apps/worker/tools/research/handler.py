"""Free public research. No model, no API key, allowlisted hosts only."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError

NAME = "web_research"
CAPABILITY = "tools.research"
TIMEOUT_SECONDS = 12
GPU = False


async def run(arguments: dict[str, Any], *, research) -> dict[str, Any]:
    query = arguments.get("q", arguments.get("query"))
    if not isinstance(query, str):
        raise CloudiatorError(400, "invalid_request_error", "q is required.", param="q")
    return await research.lookup(query, arguments.get("sources"))
