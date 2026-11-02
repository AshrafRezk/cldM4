"""X-Twilio-Signature validation.

Twilio signs the URL it requested plus the POST params sorted by name:
base64(HMAC-SHA1(auth_token, url + k1 + v1 + k2 + v2 ...)). The worker sits
behind cloudflared on 127.0.0.1, so the URL is rebuilt from PUBLIC_BASE_URL,
never from the Host header the tunnel forwarded.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Iterable


def compute_signature(auth_token: str, url: str, params: Iterable[tuple[str, str]]) -> str:
    payload = url + "".join(name + value for name, value in sorted(params, key=lambda kv: kv[0]))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def is_valid(
    auth_token: str | None,
    url: str,
    params: Iterable[tuple[str, str]],
    signature: str | None,
) -> bool:
    if not auth_token or not signature:
        return False
    expected = compute_signature(auth_token, url, list(params))
    return hmac.compare_digest(expected, signature)
