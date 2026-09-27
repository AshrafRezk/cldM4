"""Nominatim geocode. Cache first, then at most 1 request per second."""

from __future__ import annotations

from typing import Any

NAME = "geocode"
CAPABILITY = "tools.maps"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any], *, maps) -> dict[str, Any]:
    queries = arguments.get("queries")
    if queries is not None:
        if not isinstance(queries, list) or not all(isinstance(item, str) for item in queries):
            from app.errors import CloudiatorError

            raise CloudiatorError(400, "invalid_request_error", "queries must be an array of strings.")
        results = await maps.geocode_many(queries)
        return {"results": results}
    query = arguments.get("q")
    if not isinstance(query, str):
        from app.errors import CloudiatorError

        raise CloudiatorError(400, "invalid_request_error", "q is required.", param="q")
    return await maps.geocode_one(query)
