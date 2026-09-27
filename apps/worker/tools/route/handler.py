"""OSRM driving route. Coordinates only; geocode first if you only have a name."""

from __future__ import annotations

from typing import Any

from app.errors import CloudiatorError

NAME = "route"
CAPABILITY = "tools.maps"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any], *, maps) -> dict[str, Any]:
    try:
        origin = (float(arguments["origin_lat"]), float(arguments["origin_lon"]))
        destination = (float(arguments["destination_lat"]), float(arguments["destination_lon"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudiatorError(
            400, "invalid_request_error", "origin and destination coordinates are required."
        ) from exc
    return await maps.route(origin, destination)
