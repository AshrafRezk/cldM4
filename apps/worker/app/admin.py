"""Admin authentication for /v1/admin/* (PLAN.md §12).

Cloudflare Access sits in front of `api.<domain>/v1/admin*` and signs a JWT into
`Cf-Access-Jwt-Assertion`. The worker verifies that signature against the team
JWKS and checks the audience, because Access in front of an origin is only a
guarantee if the origin refuses requests that did not come through it.

`ADMIN_TOKEN` is a loopback-only break-glass for the day Access itself is the
broken thing. "Loopback" needs care: cloudflared connects to 127.0.0.1, so a
tunnelled request also arrives from a loopback address. What distinguishes a
genuine local request over SSH is the absence of the hop headers Cloudflare
always adds.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from typing import Any

import httpx
import jwt

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.admin")

ACCESS_JWT_HEADER = "cf-access-jwt-assertion"
ADMIN_TOKEN_HEADER = "x-admin-token"
JWKS_PATH = "/cdn-cgi/access/certs"
JWKS_TTL_SECONDS = 600.0
JWKS_REFETCH_SECONDS = 60.0
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
# Present on anything that came through cloudflared, and not removable by a
# caller: Cloudflare sets them at the edge and cloudflared adds its own.
TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "cf-ipcountry")


def admin_forbidden(message: str) -> CloudiatorError:
    return CloudiatorError(403, "scope_denied", message, param="Cf-Access-Jwt-Assertion")


def arrived_on_loopback(request) -> bool:
    """True only for a request that did not traverse the tunnel."""
    client = request.client.host if request.client else None
    if client not in LOOPBACK_HOSTS:
        return False
    return not any(header in request.headers for header in TUNNEL_HEADERS)


class AccessVerifier:
    """Validates a Cloudflare Access JWT against the team JWKS."""

    def __init__(self, settings, *, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._last_forced = float("-inf")

    @property
    def configured(self) -> bool:
        return bool(self.settings.cf_access_team_domain and self.settings.cf_access_aud)

    @property
    def issuer(self) -> str:
        domain = (self.settings.cf_access_team_domain or "").strip().rstrip("/")
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain
        return f"https://{domain}"

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _jwks(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if force:
            # An unknown kid means Access rotated its signing keys — or that a
            # caller is sending random ones to make the worker hammer the JWKS
            # endpoint. One forced refetch per minute covers the first and starves
            # the second.
            if now - self._last_forced < JWKS_REFETCH_SECONDS:
                return self._keys
            self._last_forced = now
        elif self._keys and now - self._fetched_at < JWKS_TTL_SECONDS:
            return self._keys
        url = f"{self.issuer}{JWKS_PATH}"
        try:
            response = await self._ensure_client().get(url)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("could not fetch the Access JWKS from %s: %s", url, exc)
            if self._keys:
                return self._keys
            raise admin_forbidden(
                "The Cloudflare Access signing keys are unreachable, so this request cannot "
                "be verified."
            ) from exc
        self._keys = {key["kid"]: key for key in document.get("keys", []) if key.get("kid")}
        self._fetched_at = now
        return self._keys

    async def verify(self, token: str) -> dict[str, Any]:
        if not self.configured:
            raise admin_forbidden(
                "CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD are not set, so an Access JWT cannot "
                "be verified. Admin is loopback-only until they are."
            )
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise admin_forbidden("The Access JWT is malformed.") from exc

        keys = await self._jwks()
        key = keys.get(kid)
        if key is None:
            # Access rotates signing keys; one refetch, rate limited.
            keys = await self._jwks(force=True)
            key = keys.get(kid)
        if key is None:
            raise admin_forbidden("The Access JWT was signed by an unknown key.")

        try:
            return jwt.decode(
                token,
                key=jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
                algorithms=["RS256"],
                audience=self.settings.cf_access_aud,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            # The reason is deliberately vague to the caller and specific in the log.
            log.warning("rejected an Access JWT: %s", exc)
            raise admin_forbidden("The Access JWT is not valid for this application.") from exc


class AdminGuard:
    def __init__(self, settings, verifier: AccessVerifier) -> None:
        self.settings = settings
        self.verifier = verifier

    async def identify(self, request) -> str:
        """Return who is calling, or raise 403. Never logs the credential."""
        token = request.headers.get(ACCESS_JWT_HEADER)
        if token:
            claims = await self.verifier.verify(token)
            return str(claims.get("email") or claims.get("common_name") or "access")

        presented = request.headers.get(ADMIN_TOKEN_HEADER)
        if presented and self.settings.admin_token:
            if not arrived_on_loopback(request):
                # A token in a header travels through logs and proxies. Over the
                # tunnel, Access is the only accepted credential.
                raise admin_forbidden(
                    "ADMIN_TOKEN is a loopback-only break-glass. Public /v1/admin/* requires "
                    "a Cloudflare Access JWT."
                )
            if hmac.compare_digest(presented, self.settings.admin_token):
                log.info("admin request authorised by the loopback break-glass token")
                return "loopback"
            raise admin_forbidden("That admin token is not valid.")

        raise admin_forbidden(
            "/v1/admin/* requires a Cloudflare Access JWT in Cf-Access-Jwt-Assertion."
        )
