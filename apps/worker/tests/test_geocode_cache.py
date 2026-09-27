"""Nominatim is cached. The second lookup does not leave the machine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.maps import MapsClient, normalize_query

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "geocode_cairo.json").read_text()
)


class Settings:
    def __init__(self, path: Path) -> None:
        self.geocode_cache_db = str(path)
        self.nominatim_user_agent = "Cloudiator/0.1 (test@example.com)"
        self.nominatim_url = "https://nominatim.test"
        self.nominatim_max_rows = 25
        self.overpass_urls = "https://overpass-a.test/interpreter,https://overpass-b.test/interpreter"
        self.osrm_url = "https://osrm.test"


def _client(tmp_path, fetch):
    client = MapsClient(Settings(tmp_path / "geocode.db"), fetch=fetch)
    client.gate.interval = 0
    return client


async def test_second_lookup_makes_no_outbound_request(tmp_path):
    calls = {"n": 0}

    async def fetch(method, url, body, user_agent):
        calls["n"] += 1
        assert user_agent.endswith("(test@example.com)")
        return {
            "status": 200,
            "json": [
                {
                    "lat": str(FIXTURE["lat"]),
                    "lon": str(FIXTURE["lon"]),
                    "display_name": FIXTURE["display_name"],
                }
            ],
            "retry_after": None,
        }

    client = _client(tmp_path, fetch)
    first = await client.geocode_one("  Cairo,   Egypt ")
    second = await client.geocode_one("cairo, egypt")

    assert first["display_name"] == FIXTURE["display_name"]
    assert abs(first["lat"] - FIXTURE["lat"]) < 1e-6
    assert second == first
    assert calls["n"] == 1
    assert normalize_query("  Cairo,   Egypt ") == normalize_query("cairo, egypt")


async def test_bulk_over_the_row_cap_is_refused(tmp_path):
    async def fetch(method, url, body, user_agent):
        raise AssertionError("bulk refusal must not call Nominatim")

    client = _client(tmp_path, fetch)
    with pytest.raises(Exception) as caught:
        await client.geocode_many(["place"] * 26)
    assert caught.value.status_code == 400
    assert "25" in caught.value.message


async def test_retry_after_is_honoured_once(tmp_path):
    seen = {"n": 0}

    async def fetch(method, url, body, user_agent):
        seen["n"] += 1
        if seen["n"] == 1:
            return {"status": 429, "json": None, "retry_after": "0"}
        return {
            "status": 200,
            "json": [{"lat": "1", "lon": "2", "display_name": "Cairo"}],
            "retry_after": None,
        }

    client = _client(tmp_path, fetch)
    result = await client.geocode_one("Cairo")
    assert result["display_name"] == "Cairo"
    assert seen["n"] == 2


async def test_overpass_fails_over_to_the_next_mirror(tmp_path):
    async def fetch(method, url, body, user_agent):
        if "overpass-a" in url:
            return {"status": 504, "json": None, "retry_after": None}
        return {
            "status": 200,
            "json": {"elements": [{"lat": 30.1, "lon": 31.2, "tags": {"name": "Cafe"}}]},
            "retry_after": None,
        }

    client = _client(tmp_path, fetch)
    places = await client.places(30.0, 31.0, "cafe")
    assert places == [{"name": "Cafe", "lat": 30.1, "lon": 31.2, "kind": "cafe"}]
