from __future__ import annotations

import ipaddress
from typing import Any

import pytest

from app.config import get_settings, reset_settings
from app.errors import ApiError
from app.ssrf import (
    assert_image_url_scheme,
    is_blocked_ip,
    load_image_bytes,
    parse_data_uri,
    resolve_public,
)
from app.vision import collect_image_urls, downscale_image, prepare_images

# 1x1 PNG
PNG = (
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    b"AAAABJRU5ErkJggg=="
)
DATA_URI = "data:image/png;base64," + PNG.decode("ascii")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDIATOR_ENV", "test")
    reset_settings()


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "10.1.2.3",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "169.254.0.1",
        "100.64.0.1",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_blocked_ips(ip: str) -> None:
    assert is_blocked_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://example.com/a.png", "ftp://x/y"])
def test_forbidden_schemes(url: str) -> None:
    with pytest.raises(ApiError) as exc:
        assert_image_url_scheme(url)
    assert exc.value.code == "url_not_allowed"


def test_https_literal_private_host() -> None:
    with pytest.raises(ApiError) as exc:
        assert_image_url_scheme("https://127.0.0.1/secret.png")
    assert exc.value.code == "url_not_allowed"


def test_https_link_local_metadata() -> None:
    with pytest.raises(ApiError) as exc:
        assert_image_url_scheme("https://169.254.169.254/latest/meta-data/")
    assert exc.value.code == "url_not_allowed"


def test_https_rfc1918() -> None:
    with pytest.raises(ApiError) as exc:
        assert_image_url_scheme("https://10.0.0.8/img.png")
    assert exc.value.code == "url_not_allowed"


@pytest.mark.asyncio
async def test_dns_to_private_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_getaddrinfo(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(0, 0, 0, "", ("169.254.169.254", 0))]

    monkeypatch.setattr("app.ssrf.asyncio.get_running_loop", lambda: type("L", (), {"getaddrinfo": fake_getaddrinfo})())
    with pytest.raises(ApiError) as exc:
        await resolve_public("evil.example")
    assert exc.value.code == "url_not_allowed"


@pytest.mark.asyncio
async def test_dns_to_loopback_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_getaddrinfo(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(0, 0, 0, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("app.ssrf.asyncio.get_running_loop", lambda: type("L", (), {"getaddrinfo": fake_getaddrinfo})())
    with pytest.raises(ApiError) as exc:
        await resolve_public("local.example")
    assert exc.value.code == "url_not_allowed"


@pytest.mark.asyncio
async def test_data_uri_is_accepted() -> None:
    settings = get_settings()
    raw = await load_image_bytes(DATA_URI, settings)
    assert raw.startswith(b"\x89PNG")
    jpeg = downscale_image(raw, settings)
    assert jpeg[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_max_four_images() -> None:
    settings = get_settings()
    content = [{"type": "image_url", "image_url": {"url": DATA_URI}} for _ in range(5)]
    with pytest.raises(ApiError) as exc:
        await prepare_images(content, settings, vision_supported=True)
    assert exc.value.code == "url_not_allowed"


def test_collect_image_urls() -> None:
    content = [
        {"type": "text", "text": "see"},
        {"type": "image_url", "image_url": {"url": DATA_URI}},
    ]
    assert collect_image_urls(content) == [DATA_URI]


def test_parse_data_uri_rejects_non_image() -> None:
    with pytest.raises(ApiError):
        parse_data_uri("data:text/html;base64,PGh0bWw+")
