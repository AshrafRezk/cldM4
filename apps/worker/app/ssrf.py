"""SSRF guard for vision image inputs (PLAN.md §10, §12).

The API is OpenAI-compatible, so `messages[].content[].image_url` is
attacker-controlled by design. Without this, a tenant points it at
`http://169.254.169.254/` or `http://127.0.0.1:11434/` and reads the response
back out through the model.

Rules:

* `https:` and `data:` only. Everything else is 400 `url_not_allowed`.
* Resolve DNS and check **every** resolved address, then connect to the
  validated address with SNI and Host preserved, so a second resolution cannot
  come back with a different answer (DNS rebinding).
* Re-check after every redirect, capped at 2 hops.
* Content-Type must be an image; 25 MB and 10s caps per fetch.
* Downscale to a 1024px long edge, JPEG q85, EXIF stripped, max 4 images.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import logging
import socket
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .errors import upload_too_large, url_not_allowed

log = logging.getLogger("cloudiator.ssrf")

ALLOWED_SCHEMES = ("https", "data")
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
CGNAT = ipaddress.ip_network("100.64.0.0/10")
JPEG_QUALITY = 85

Resolver = Callable[[str, int], Awaitable[list[Any]]]


@dataclass(frozen=True)
class FetchedImage:
    data: bytes
    content_type: str
    source: str


def blocked_reason(address: str) -> str | None:
    """Return why an IP literal must not be fetched, or None if it is allowed."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"{address!r} is not an IP address"

    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return blocked_reason(str(ip.ipv4_mapped))
        if ip in NAT64_PREFIX:
            embedded = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
            return blocked_reason(str(embedded)) or "NAT64-embedded address"
        if ip.sixtofour is not None:
            return blocked_reason(str(ip.sixtofour)) or "6to4-embedded address"
        if ip.teredo is not None:
            return blocked_reason(str(ip.teredo[0])) or "Teredo-embedded address"

    if ip.is_unspecified:
        return "unspecified address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address (cloud metadata lives here)"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_reserved:
        return "reserved address"
    if ip.version == 4 and ip in CGNAT:
        return "CGNAT shared address space"
    if ip.is_private:
        return "private address"
    if not ip.is_global:
        return "not a globally routable address"
    return None


async def _default_resolver(host: str, port: int) -> list[Any]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)


async def resolve_and_validate(
    host: str, port: int, *, resolver: Resolver | None = None
) -> str:
    """Resolve a hostname and reject if **any** answer is non-public.

    Returns the first validated address, which the caller connects to directly.
    """
    if not host:
        raise url_not_allowed("The image URL has no host.")

    literal = None
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    if literal is not None:
        reason = blocked_reason(str(literal))
        if reason:
            raise url_not_allowed(f"Refusing to fetch {host}: {reason}.")
        return str(literal)

    resolve = resolver or _default_resolver
    try:
        infos = await resolve(host, port)
    except (socket.gaierror, OSError) as exc:
        raise url_not_allowed(f"Could not resolve {host}.") from exc
    if not infos:
        raise url_not_allowed(f"Could not resolve {host}.")

    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        address = sockaddr[0]
        reason = blocked_reason(address)
        if reason:
            raise url_not_allowed(f"Refusing to fetch {host}: it resolves to {address}, a {reason}.")
        addresses.append(address)

    if not addresses:
        raise url_not_allowed(f"Could not resolve {host}.")
    return addresses[0]


def validate_url(url: str) -> tuple[str, str, int]:
    """Check the scheme and return (url, host, port)."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise url_not_allowed(
            f"Scheme {parts.scheme or '(none)'}: is not allowed. Use https: or a data: URI."
        )
    if parts.scheme != "https":
        raise url_not_allowed("Only https: URLs are fetched.")
    if not parts.hostname:
        raise url_not_allowed("The image URL has no host.")
    return url, parts.hostname, parts.port or 443


def decode_data_uri(url: str, *, max_bytes: int) -> FetchedImage:
    header, _, payload = url[len("data:") :].partition(",")
    if not payload:
        raise url_not_allowed("The data: URI has no payload.")
    content_type = header.split(";")[0] or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise url_not_allowed(f"data: URI is {content_type}, not an image.")
    if not header.endswith(";base64") and ";base64;" not in header:
        raise url_not_allowed("Only base64-encoded data: URIs are accepted.")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise url_not_allowed("The data: URI is not valid base64.") from exc
    if len(data) > max_bytes:
        raise upload_too_large(max_bytes)
    return FetchedImage(data=data, content_type=content_type, source="data:")


def _pinned_url(url: str, address: str) -> str:
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


async def fetch_image(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
) -> FetchedImage:
    if url.startswith("data:"):
        return decode_data_uri(url, max_bytes=max_bytes)

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        current = url
        for _ in range(max_redirects + 1):
            current, host, port = validate_url(current)
            address = await resolve_and_validate(host, port, resolver=resolver)
            request_url = _pinned_url(current, address)
            headers = {"Host": urlsplit(current).netloc, "Accept": "image/*"}

            response = await http.get(
                request_url,
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
                extensions={"sni_hostname": host},
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise url_not_allowed("Redirect without a Location header.")
                current = urljoin(current, location)
                continue

            if response.status_code >= 400:
                raise url_not_allowed(
                    f"The image URL returned HTTP {response.status_code}."
                )
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                raise url_not_allowed(
                    f"The URL returned {content_type or 'an unknown type'}, not an image."
                )
            data = response.content
            if len(data) > max_bytes:
                raise upload_too_large(max_bytes)
            return FetchedImage(data=data, content_type=content_type, source=url)

        raise url_not_allowed(f"More than {max_redirects} redirects.")
    finally:
        if owns_client:
            await http.aclose()


def downscale_to_jpeg(data: bytes, *, max_edge: int) -> bytes:
    """Long edge <= max_edge, JPEG q85, EXIF dropped.

    A 12 MP phone photo is thousands of image tokens and silently overflows a
    4k context, dropping the actual question.
    """
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            converted = image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types
        raise url_not_allowed("The image could not be decoded.") from exc

    converted.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buffer = BytesIO()
    converted.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def validate_image_inputs(messages: list[dict[str, Any]], *, settings) -> list[str]:
    """Cheap pre-validation: no DNS, no fetch, no decode.

    Runs before the vision-capability check so a forbidden URL is always
    `url_not_allowed` rather than `model_not_found` on an appliance whose
    default model happens to have no vision support. A caller who sent
    `file:///etc/passwd` needs to hear that, not a note about models.
    """
    urls = extract_image_urls(messages)
    if len(urls) > settings.vision_max_images:
        raise url_not_allowed(
            f"{len(urls)} images in one request exceeds the limit of "
            f"{settings.vision_max_images}."
        )
    for url in urls:
        if not url.startswith("data:"):
            validate_url(url)
    return urls


def extract_image_urls(messages: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                raw = part.get("image_url")
                url = raw.get("url") if isinstance(raw, dict) else raw
                if not isinstance(url, str) or not url:
                    raise url_not_allowed("image_url.url must be a non-empty string.")
                urls.append(url)
    return urls


async def prepare_messages_for_ollama(
    messages: list[dict[str, Any]],
    *,
    settings,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
) -> list[dict[str, Any]]:
    """Flatten OpenAI content parts and attach downscaled images per message."""
    total_images = len(extract_image_urls(messages))
    if total_images > settings.vision_max_images:
        raise url_not_allowed(
            f"{total_images} images in one request exceeds the limit of "
            f"{settings.vision_max_images}."
        )

    prepared: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            prepared.append(dict(message))
            continue

        texts: list[str] = []
        images: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                texts.append(str(part))
                continue
            if part.get("type") == "image_url":
                raw = part.get("image_url")
                url = raw.get("url") if isinstance(raw, dict) else raw
                fetched = await fetch_image(
                    url,
                    max_bytes=settings.vision_max_bytes,
                    timeout=settings.vision_fetch_timeout_seconds,
                    max_redirects=settings.vision_max_redirects,
                    client=client,
                    resolver=resolver,
                )
                resized = downscale_to_jpeg(fetched.data, max_edge=settings.vision_max_edge_px)
                images.append(base64.b64encode(resized).decode("ascii"))
            else:
                texts.append(str(part.get("text", "")))

        new_message = {key: value for key, value in message.items() if key != "content"}
        new_message["content"] = "\n".join(text for text in texts if text)
        if images:
            new_message["images"] = images
        prepared.append(new_message)
    return prepared
