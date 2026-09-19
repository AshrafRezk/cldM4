"""SSRF guard (PLAN.md §10, §12).

The image URL is attacker-controlled by design, so every one of these cases is
a live exploit if it passes.
"""

from __future__ import annotations

import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.errors import CloudiatorError
from app.ssrf import (
    blocked_reason,
    decode_data_uri,
    downscale_to_jpeg,
    fetch_image,
    prepare_messages_for_ollama,
    resolve_and_validate,
    validate_url,
)

BLOCKED = [
    "127.0.0.1",
    "127.1.2.3",
    "0.0.0.0",
    "10.0.0.7",
    "172.16.0.1",
    "192.168.1.10",
    "169.254.169.254",
    "100.64.0.1",
    "224.0.0.1",
    "240.0.0.1",
    "::1",
    "::",
    "fc00::1",
    "fe80::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "64:ff9b::7f00:1",
]

ALLOWED = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]


def png_bytes(width: int = 64, height: int = 32) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def data_uri(data: bytes, content_type: str = "image/png") -> str:
    return f"data:{content_type};base64," + base64.b64encode(data).decode("ascii")


@pytest.mark.parametrize("address", BLOCKED)
def test_private_and_metadata_addresses_are_blocked(address):
    assert blocked_reason(address) is not None, f"{address} must be blocked"


@pytest.mark.parametrize("address", ALLOWED)
def test_public_addresses_are_allowed(address):
    assert blocked_reason(address) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/cat.png",
        "file:///etc/passwd",
        "ftp://example.com/cat.png",
        "gopher://example.com/",
        "javascript:alert(1)",
        "//example.com/cat.png",
        "https:///nohost.png",
    ],
)
def test_only_https_urls_are_fetched(url):
    with pytest.raises(CloudiatorError) as caught:
        validate_url(url)
    assert caught.value.code == "url_not_allowed"
    assert caught.value.status_code == 400


def test_https_url_is_accepted_by_the_scheme_check():
    url, host, port = validate_url("https://images.example.com/cat.png")
    assert (host, port) == ("images.example.com", 443)


async def test_literal_metadata_ip_is_rejected_without_dns():
    with pytest.raises(CloudiatorError) as caught:
        await resolve_and_validate("169.254.169.254", 443)
    assert "link-local" in caught.value.message


async def test_hostname_resolving_to_loopback_is_rejected():
    async def resolver(host, port):
        return [(2, 1, 6, "", ("127.0.0.1", port))]

    with pytest.raises(CloudiatorError) as caught:
        await resolve_and_validate("localtest.me", 443, resolver=resolver)
    assert "127.0.0.1" in caught.value.message


async def test_a_single_private_answer_poisons_the_whole_resolution():
    async def resolver(host, port):
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("10.1.2.3", port)),
        ]

    with pytest.raises(CloudiatorError):
        await resolve_and_validate("split-horizon.example", 443, resolver=resolver)


async def test_public_hostname_resolves_to_a_validated_address():
    async def resolver(host, port):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    assert await resolve_and_validate("example.com", 443, resolver=resolver) == "93.184.216.34"


async def test_fetch_rejects_plain_http():
    with pytest.raises(CloudiatorError) as caught:
        await fetch_image(
            "http://example.com/cat.png", max_bytes=1000, timeout=1, max_redirects=2
        )
    assert caught.value.code == "url_not_allowed"


async def public_resolver(host, port):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


async def test_redirect_into_the_private_network_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1:11434/api/tags"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CloudiatorError) as caught:
            await fetch_image(
                "https://images.example.com/cat.png",
                max_bytes=10_000,
                timeout=1,
                max_redirects=2,
                client=client,
                resolver=public_resolver,
            )
    finally:
        await client.aclose()
    assert caught.value.code == "url_not_allowed"


async def test_redirect_to_a_metadata_host_is_rejected_after_the_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        if "second" not in str(request.url):
            return httpx.Response(302, headers={"location": "https://second.example/img.png"})
        return httpx.Response(200, content=png_bytes(), headers={"content-type": "image/png"})

    async def resolver(host, port):
        if host == "second.example":
            return [(2, 1, 6, "", ("169.254.169.254", port))]
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CloudiatorError) as caught:
            await fetch_image(
                "https://first.example/img.png",
                max_bytes=10_000,
                timeout=1,
                max_redirects=2,
                client=client,
                resolver=resolver,
            )
    finally:
        await client.aclose()
    assert "169.254.169.254" in caught.value.message


async def test_redirect_chain_is_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://images.example.com/next.png"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CloudiatorError) as caught:
            await fetch_image(
                "https://images.example.com/cat.png",
                max_bytes=10_000,
                timeout=1,
                max_redirects=2,
                client=client,
                resolver=public_resolver,
            )
    finally:
        await client.aclose()
    assert "redirect" in caught.value.message.lower()


async def test_non_image_content_type_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CloudiatorError) as caught:
            await fetch_image(
                "https://images.example.com/cat.png",
                max_bytes=10_000,
                timeout=1,
                max_redirects=2,
                client=client,
                resolver=public_resolver,
            )
    finally:
        await client.aclose()
    assert "not an image" in caught.value.message


async def test_oversized_image_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=png_bytes(400, 400), headers={"content-type": "image/png"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CloudiatorError) as caught:
            await fetch_image(
                "https://images.example.com/cat.png",
                max_bytes=10,
                timeout=1,
                max_redirects=2,
                client=client,
                resolver=public_resolver,
            )
    finally:
        await client.aclose()
    assert caught.value.status_code == 413


def test_data_uri_must_be_an_image():
    with pytest.raises(CloudiatorError):
        decode_data_uri("data:text/html;base64,PHNjcmlwdD4=", max_bytes=1000)


def test_data_uri_must_be_base64():
    with pytest.raises(CloudiatorError):
        decode_data_uri("data:image/png,not-base64", max_bytes=1000)


def test_data_uri_image_is_accepted():
    fetched = decode_data_uri(data_uri(png_bytes()), max_bytes=100_000)
    assert fetched.content_type == "image/png"
    assert fetched.data.startswith(b"\x89PNG")


def test_downscale_caps_the_long_edge_and_strips_exif():
    original = png_bytes(2000, 1500)
    resized = downscale_to_jpeg(original, max_edge=1024)
    with Image.open(BytesIO(resized)) as image:
        assert max(image.size) == 1024
        assert image.format == "JPEG"
        assert not image.getexif()


def test_downscale_rejects_a_non_image_payload():
    with pytest.raises(CloudiatorError):
        downscale_to_jpeg(b"definitely not an image", max_edge=1024)


async def test_prepare_messages_flattens_content_and_attaches_images(settings):
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is in this photo?"},
                {"type": "image_url", "image_url": {"url": data_uri(png_bytes(2000, 1000))}},
            ],
        }
    ]

    prepared = await prepare_messages_for_ollama(messages, settings=settings)

    assert prepared[0]["content"] == "what is in this photo?"
    assert len(prepared[0]["images"]) == 1
    decoded = base64.b64decode(prepared[0]["images"][0])
    with Image.open(BytesIO(decoded)) as image:
        assert max(image.size) == settings.vision_max_edge_px


async def test_more_than_four_images_is_rejected(settings):
    parts = [
        {"type": "image_url", "image_url": {"url": data_uri(png_bytes())}}
        for _ in range(settings.vision_max_images + 1)
    ]
    messages = [{"role": "user", "content": parts}]

    with pytest.raises(CloudiatorError) as caught:
        await prepare_messages_for_ollama(messages, settings=settings)

    assert caught.value.code == "url_not_allowed"


async def test_plain_string_messages_pass_through_untouched(settings):
    messages = [{"role": "user", "content": "say hi"}]
    assert await prepare_messages_for_ollama(messages, settings=settings) == messages
