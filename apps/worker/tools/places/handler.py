"""Overpass nearby search, with failover across OVERPASS_URLS."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError

NAME = "places_nearby"
CAPABILITY = "tools.maps"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any], *, maps) -> dict[str, Any]:
    try:
        lat = float(arguments["lat"])
        lon = float(arguments["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudiatorError(400, "invalid_request_error", "lat and lon are required.") from exc
    kind = arguments.get("kind")
    if not isinstance(kind, str):
        raise CloudiatorError(400, "invalid_request_error", "kind is required.")
    places = await maps.places(lat, lon, kind)
    return {"places": places}
