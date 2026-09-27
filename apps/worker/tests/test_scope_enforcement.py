"""A key without the scope gets 403, not a tool result and not a 200."""

from __future__ import annotations

import base64

import pytest

from app import main
from tests.ocr_fixture import GOLDEN


@pytest.fixture()
def client(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    return make_client(headers)


async def test_ocr_without_scope_is_403(client):
    async with client:
        response = await client.post("/v1/tools/ocr", json={"image_url": "https://example.com/a.png"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_geocode_without_maps_scope_is_403(client):
    async with client:
        response = await client.post("/v1/tools/geocode", json={"q": "Cairo"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_scoped_key_reaches_the_handler(make_client, install_key, monkeypatch):
    async def fetch(method, url, body, user_agent):
        assert "test@example.com" in user_agent
        return {
            "status": 200,
            "json": [{"lat": "30.0443879", "lon": "31.2357257", "display_name": "Cairo, Egypt"}],
            "retry_after": None,
        }

    monkeypatch.setattr(main.tool_runner.maps, "fetch", fetch)
    _record, headers = install_key(capabilities=["tools.maps"])
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/geocode", json={"q": "Cairo, Egypt"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Cairo, Egypt"


async def test_ocr_matches_the_golden_fixture(make_client, install_key, monkeypatch):
    monkeypatch.setenv("CLOUDIATOR_OCR_BACKEND", "tests.ocr_fixture:recognize")
    _record, headers = install_key(capabilities=["tools.ocr"])
    image = base64.b64encode(b"png-bytes").decode()
    async with make_client(headers) as client:
        response = await client.post("/v1/tools/ocr", json={"image_base64": image})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == GOLDEN
