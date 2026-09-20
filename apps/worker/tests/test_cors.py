"""CORS for the dashboard playground. Apex callouts do not send Origin."""

from __future__ import annotations

import pytest

from app import main
from app.cors import cors_headers, dashboard_origin_from_public_base


def test_dashboard_origin_is_app_sibling_of_api():
    assert (
        dashboard_origin_from_public_base("https://api.cloudiator.org")
        == "https://app.cloudiator.org"
    )
    assert dashboard_origin_from_public_base("http://127.0.0.1:8080") == ""


def test_unknown_origin_gets_no_cors_headers():
    assert cors_headers("https://evil.example", frozenset({"https://app.cloudiator.org"})) == {}


def test_settings_derive_dashboard_origin_from_public_base(settings):
    assert settings.dashboard_origin == "https://app.cloudiator.test"


@pytest.mark.asyncio
async def test_preflight_from_the_dashboard_is_204_without_a_key():
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        response = await client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://app.cloudiator.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "https://app.cloudiator.test"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.asyncio
async def test_chat_from_the_dashboard_origin_gets_cors_on_the_response(cached_key):
    from httpx import ASGITransport, AsyncClient

    _, headers = cached_key
    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8080", headers=headers
    ) as client:
        response = await client.get(
            "/v1/health",
            headers={"Origin": "https://app.cloudiator.test"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.cloudiator.test"


@pytest.mark.asyncio
async def test_a_foreign_origin_is_not_reflected():
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        response = await client.get(
            "/v1/health",
            headers={"Origin": "https://evil.example"},
        )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
