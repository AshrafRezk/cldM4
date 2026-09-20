"""Browser CORS for the dashboard playground (PLAN.md §10).

Salesforce Apex does not send Origin and does not need CORS. The playground on
app.<domain> does: it calls https://api.<domain>/v1/chat/completions from the
browser with the minted key. Inference still runs on the Mini; this module only
adds headers.

Preflight OPTIONS has no Authorization header, so per-key allowed_origins cannot
decide it. The allowlist is the dashboard origin derived from PUBLIC_BASE_URL
(api.X → app.X), plus optional CORS_EXTRA_ORIGINS. Unknown origins get no CORS
headers and the browser blocks them; the request itself is not failed.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

ALLOW_METHODS = "GET, POST, OPTIONS"
ALLOW_HEADERS = "Authorization, Content-Type, X-Request-Id"
EXPOSE_HEADERS = (
    "X-Request-Id, x-cloudiator-stream-downgraded, x-cloudiator-tool-iterations"
)


def dashboard_origin_from_public_base(public_base_url: str) -> str:
    parsed = urlparse(public_base_url)
    host = parsed.netloc
    if not host.startswith("api."):
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://app.{host[4:]}"


def allowed_origins(settings) -> frozenset[str]:
    origins: set[str] = set()
    derived = (settings.dashboard_origin or "").rstrip("/")
    if derived:
        origins.add(derived)
    extra = os.environ.get("CORS_EXTRA_ORIGINS") or ""
    for item in extra.split(","):
        item = item.strip().rstrip("/")
        if item:
            origins.add(item)
    return frozenset(origins)


def cors_headers(origin: str | None, allowed: frozenset[str]) -> dict[str, str]:
    if not origin:
        return {}
    candidate = origin.rstrip("/")
    if candidate not in allowed:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": ALLOW_METHODS,
        "Access-Control-Allow-Headers": ALLOW_HEADERS,
        "Access-Control-Expose-Headers": EXPOSE_HEADERS,
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }
