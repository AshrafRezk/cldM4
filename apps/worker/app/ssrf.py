"""SSRF guard for vision image_url (PLAN.md §10 / §12)."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.errors import upload_too_large, url_not_allowed

log = logging.getLogger("cloudiator.ssrf")

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_LINK_LOCAL_V4 = ipaddress.ip_network("169.254.0.0/16")
_ULA = ipaddress.ip_network("fc00::/7")
_V6_LOOPBACK = ipaddress.ip_network("::1/128")
_V6_LINK_LOCAL = ipaddress.ip_network("fe80::/10")
_V6_MULTICAST = ipaddress.ip_network("ff00::/8")
_METADATA_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/bmp",
    "image/tiff",
}


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_blocked_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_unspecified or ip.is_reserved:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in _CGNAT or ip in _LINK_LOCAL_V4:
            return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in _ULA or ip in _V6_LOOPBACK or ip in _V6_LINK_LOCAL or ip in _V6_MULTICAST:
            return True
    return False


def assert_public_hostname(host: str) -> None:
    lowered = host.strip("[]").lower().rstrip(".")
    if lowered in _METADATA_HOSTS or lowered.endswith(".local"):
        raise url_not_allowed(f"Host {host!r} is not allowed")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return
    if is_blocked_ip(ip):
        raise url_not_allowed(f"Address {host} is not allowed")


async def resolve_public(host: str) -> list[str]:
    assert_public_hostname(host)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise url_not_allowed(f"Could not resolve host {host!r}") from exc
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip_txt = sockaddr[0]
        ip = ipaddress.ip_address(ip_txt)
        if is_blocked_ip(ip):
            raise url_not_allowed(f"Host {host} resolved to blocked address {ip}")
        addresses.append(str(ip))
    if not addresses:
        raise url_not_allowed(f"Host {host} resolved to no addresses")
    return addresses


def parse_data_uri(url: str) -> tuple[str, bytes]:
    if not url.startswith("data:"):
        raise url_not_allowed("Not a data URI")
    header, _, rest = url.partition(",")
    meta = header[5:]
    if ";base64" not in meta:
        raise url_not_allowed("Only base64 data: image URIs are accepted")
    mime = meta.split(";")[0] or "application/octet-stream"
    if mime.split(";")[0] not in ALLOWED_IMAGE_TYPES and not mime.startswith("image/"):
        raise url_not_allowed(f"data: URI content type {mime!r} is not an image")
    try:
        raw = base64.b64decode(rest, validate=False)
    except Exception as exc:
        raise url_not_allowed("Invalid base64 in data: URI") from exc
    return mime, raw


def assert_image_url_scheme(url: str) -> None:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"http", "file", "ftp", "gopher", "dict", "sftp", "ssh"}:
        raise url_not_allowed(f"Scheme {scheme}:// is not allowed; use https:// or data:")
    if scheme == "data":
        return
    if scheme != "https":
        raise url_not_allowed("Only https:// and data: image URLs are allowed")
    if not parsed.hostname:
        raise url_not_allowed("Image URL is missing a hostname")
    assert_public_hostname(parsed.hostname)


async def fetch_https_image(url: str, settings: Settings, *, redirects_left: int = 2) -> bytes:
    assert_image_url_scheme(url)
    parsed = urlparse(url)
    await resolve_public(parsed.hostname or "")
    timeout = httpx.Timeout(settings.vision_fetch_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        response = await client.get(url, headers={"Accept": "image/*,application/octet-stream"})
    if response.status_code in {301, 302, 303, 307, 308}:
        location = response.headers.get("location")
        if not location or redirects_left <= 0:
            raise url_not_allowed("Image URL redirected too many times or without Location")
        next_url = str(response.url.join(location))
        log.info("vision redirect -> %s", next_url)
        return await fetch_https_image(next_url, settings, redirects_left=redirects_left - 1)
    if response.status_code >= 400:
        raise url_not_allowed(f"Image fetch failed with HTTP {response.status_code}")
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type not in ALLOWED_IMAGE_TYPES and not content_type.startswith("image/"):
        raise url_not_allowed(f"Content-Type {content_type!r} is not an image")
    data = response.content
    if len(data) > settings.vision_max_bytes:
        raise upload_too_large(f"Image exceeds {settings.vision_max_bytes} bytes")
    return data


async def load_image_bytes(url: str, settings: Settings) -> bytes:
    assert_image_url_scheme(url)
    if url.startswith("data:"):
        _mime, raw = parse_data_uri(url)
        if len(raw) > settings.vision_max_bytes:
            raise upload_too_large(f"Image exceeds {settings.vision_max_bytes} bytes")
        return raw
    return await fetch_https_image(url, settings)
