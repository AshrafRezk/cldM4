"""Nominatim, Overpass, and OSRM.

Nominatim's public instance bans clients with a generic User-Agent and clients
faster than 1 request per second, and the ban hits the home IP. The cache is
checked first. The limiter applies to cache misses only.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from .errors import CloudiatorError

CACHE_TTL_SECONDS = 30 * 24 * 3600
_SPACE = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    return _SPACE.sub(" ", query.strip()).casefold()


class GeocodeCache:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        with sqlite3.connect(path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS geocode_cache (
                  q TEXT PRIMARY KEY,
                  body TEXT NOT NULL,
                  stored_at INTEGER NOT NULL
                )
                """
            )

    def get(self, query: str, *, now: float | None = None) -> dict[str, Any] | None:
        key = normalize_query(query)
        if not key:
            return None
        moment = int(now if now is not None else time.time())
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT body, stored_at FROM geocode_cache WHERE q = ?", (key,)
            ).fetchone()
        if row is None or moment - int(row[1]) > CACHE_TTL_SECONDS:
            return None
        return json.loads(row[0])

    def put(self, query: str, body: dict[str, Any], *, now: float | None = None) -> None:
        key = normalize_query(query)
        moment = int(now if now is not None else time.time())
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                INSERT INTO geocode_cache (q, body, stored_at) VALUES (?, ?, ?)
                ON CONFLICT(q) DO UPDATE SET body = excluded.body, stored_at = excluded.stored_at
                """,
                (key, json.dumps(body), moment),
            )


class RateGate:
    """One in-flight OSM request per second, process-wide."""

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next = 0.0
        self.waits = 0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                self.waits += 1
                await asyncio.sleep(delay)
            self._next = time.monotonic() + self.interval


def _retry_after_seconds(header: str | None) -> float | None:
    if not header:
        return None
    header = header.strip()
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(header).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0.0, moment - time.time())


class MapsClient:
    def __init__(self, settings, *, fetch: Callable[..., Awaitable[Any]] | None = None) -> None:
        self.settings = settings
        self.cache = GeocodeCache(settings.geocode_cache_db)
        self.gate = RateGate()
        self.fetch = fetch or self._http_fetch
        self.outbound = 0

    def _user_agent(self) -> str:
        agent = (self.settings.nominatim_user_agent or "").strip()
        if not agent or "you@example.com" in agent or "@" not in agent:
            raise CloudiatorError(
                500,
                "internal_error",
                "NOMINATIM_USER_AGENT must be a real monitored mailbox. "
                "A generic User-Agent gets the home IP blocked.",
                error_type="server_error",
            )
        return agent

    async def geocode_one(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise CloudiatorError(400, "invalid_request_error", "q is required.", param="q")
        cached = self.cache.get(query)
        if cached is not None:
            return cached
        await self.gate.wait()
        url = (
            f"{self.settings.nominatim_url.rstrip('/')}/search"
            f"?q={_query(query)}&format=jsonv2&limit=1"
        )
        payload = await self._get_json(url)
        if not isinstance(payload, list) or not payload:
            raise CloudiatorError(404, "not_found", f"No geocode result for {query!r}.")
        hit = payload[0]
        body = {
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "display_name": hit.get("display_name") or query,
        }
        self.cache.put(query, body)
        return body

    async def geocode_many(self, queries: list[str]) -> list[dict[str, Any]]:
        if len(queries) > self.settings.nominatim_max_rows:
            raise CloudiatorError(
                400,
                "invalid_request_error",
                f"At most {self.settings.nominatim_max_rows} geocodes per request. "
                "Bulk use of the public Nominatim instance is against its policy; "
                "self-host or buy a geocoder for larger lists.",
                param="queries",
            )
        return [await self.geocode_one(query) for query in queries]

    async def places(self, lat: float, lon: float, kind: str) -> list[dict[str, Any]]:
        kind = kind.strip().lower()
        if not kind or not re.fullmatch(r"[a-z0-9_]+", kind):
            raise CloudiatorError(400, "invalid_request_error", "kind must be a simple amenity name.")
        query = (
            f"[out:json][timeout:25];"
            f'node["amenity"="{kind}"](around:1000,{lat},{lon});'
            f"out 20;"
        )
        urls = [item.strip() for item in self.settings.overpass_urls.split(",") if item.strip()]
        if not urls:
            raise CloudiatorError(500, "internal_error", "OVERPASS_URLS is empty.", error_type="server_error")
        last_error: Exception | None = None
        for url in urls:
            try:
                await self.gate.wait()
                payload = await self._post_json(url, query)
                elements = payload.get("elements") if isinstance(payload, dict) else None
                if not isinstance(elements, list):
                    raise CloudiatorError(502, "not_supported", "Overpass returned no elements.")
                places = []
                for element in elements:
                    tags = element.get("tags") or {}
                    if "lat" not in element or "lon" not in element:
                        continue
                    places.append(
                        {
                            "name": tags.get("name") or kind,
                            "lat": float(element["lat"]),
                            "lon": float(element["lon"]),
                            "kind": kind,
                        }
                    )
                return places
            except CloudiatorError as exc:
                last_error = exc
                continue
        raise last_error or CloudiatorError(502, "not_supported", "Overpass failed.")

    async def route(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
        olat, olon = origin
        dlat, dlon = destination
        url = (
            f"{self.settings.osrm_url.rstrip('/')}/route/v1/driving/"
            f"{olon},{olat};{dlon},{dlat}?overview=false"
        )
        await self.gate.wait()
        payload = await self._get_json(url)
        routes = payload.get("routes") if isinstance(payload, dict) else None
        if not routes:
            raise CloudiatorError(404, "not_found", "No driving route for those points.")
        first = routes[0]
        return {"distance_m": float(first["distance"]), "duration_s": float(first["duration"])}

    async def _get_json(self, url: str) -> Any:
        return await self._send("GET", url, None)

    async def _post_json(self, url: str, body: str) -> Any:
        return await self._send("POST", url, body)

    async def _send(self, method: str, url: str, body: str | None) -> Any:
        response = await self._once(method, url, body)
        if response["status"] == 429:
            delay = _retry_after_seconds(response.get("retry_after"))
            if delay is not None and delay <= 5:
                await asyncio.sleep(delay)
                response = await self._once(method, url, body)
            if response["status"] == 429:
                retry = int(_retry_after_seconds(response.get("retry_after")) or 5)
                raise CloudiatorError(
                    429,
                    "insufficient_quota",
                    "The map service asked us to slow down.",
                    error_type="rate_limit_error",
                    retry_after=max(1, retry),
                )
        if response["status"] >= 400:
            raise CloudiatorError(
                502,
                "not_supported",
                f"Map service returned HTTP {response['status']}.",
                error_type="server_error",
            )
        return response["json"]

    async def _once(self, method: str, url: str, body: str | None) -> dict[str, Any]:
        self.outbound += 1
        return await self.fetch(method, url, body, self._user_agent())

    async def _http_fetch(self, method: str, url: str, body: str | None, user_agent: str) -> dict[str, Any]:
        import httpx

        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                response = await client.post(url, content=f"data={body}", headers=headers)
            else:
                response = await client.get(url, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return {
            "status": response.status_code,
            "json": payload,
            "retry_after": response.headers.get("retry-after"),
        }


def _query(value: str) -> str:
    from urllib.parse import quote

    return quote(value)
