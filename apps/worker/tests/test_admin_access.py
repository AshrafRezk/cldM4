"""/v1/admin/* authentication (PLAN.md §12).

Cloudflare Access in front of an origin is only a guarantee if the origin
refuses requests that did not come through it, so the worker verifies the
`Cf-Access-Jwt-Assertion` signature against the team JWKS and checks the
audience itself.

`ADMIN_TOKEN` is the break-glass for the day Access is the broken thing, and the
trap it has to avoid is subtle: cloudflared connects to 127.0.0.1, so a
tunnelled request also arrives from a loopback address. What separates a genuine
local request over SSH is the absence of Cloudflare's hop headers.
"""

from __future__ import annotations

import dataclasses
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import main
from app.admin import AccessVerifier, AdminGuard, arrived_on_loopback

TEAM_DOMAIN = "cloudiator.cloudflareaccess.com"
AUD = "aud-tag-for-the-api-app"
ISSUER = f"https://{TEAM_DOMAIN}"


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(private_key, kid: str) -> dict:
    document = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    document.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return document


def sign(private_key, kid: str, **claims) -> str:
    payload = {
        "aud": AUD,
        "iss": ISSUER,
        "email": "ashraf@example.com",
        "iat": int(time.time()) - 5,
        "exp": int(time.time()) + 300,
    }
    payload.update(claims)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


class Jwks:
    """A JWKS endpoint that counts fetches, so rotation can be tested."""

    def __init__(self, keys: list[dict], *, status: int = 200) -> None:
        self.keys = keys
        self.status = status
        self.fetches = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/cdn-cgi/access/certs"
            self.fetches += 1
            if self.status != 200:
                return httpx.Response(self.status, text="nope")
            return httpx.Response(200, json={"keys": self.keys})

        return httpx.MockTransport(handler)


@pytest.fixture()
def access_settings():
    return dataclasses.replace(
        main.settings,
        cf_access_team_domain=TEAM_DOMAIN,
        cf_access_aud=AUD,
        admin_token=None,
    )


def install_guard(monkeypatch, settings, jwks: Jwks) -> AdminGuard:
    verifier = AccessVerifier(
        settings, client=httpx.AsyncClient(transport=jwks.transport(), timeout=2.0)
    )
    guard = AdminGuard(settings, verifier)
    monkeypatch.setattr(main, "admin_guard", guard)
    return guard


# ---- Access JWT ----------------------------------------------------------


async def test_a_valid_access_jwt_is_accepted(make_client, monkeypatch, access_settings):
    key = make_key()
    jwks = Jwks([jwk_for(key, "kid-1")])
    install_guard(monkeypatch, access_settings, jwks)

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush",
            headers={"Cf-Access-Jwt-Assertion": sign(key, "kid-1")},
        )

    assert response.status_code == 200
    assert jwks.fetches == 1


async def test_the_jwks_is_cached_across_requests(make_client, monkeypatch, access_settings):
    key = make_key()
    jwks = Jwks([jwk_for(key, "kid-1")])
    install_guard(monkeypatch, access_settings, jwks)

    async with make_client() as client:
        for _ in range(3):
            token = sign(key, "kid-1")
            assert (
                await client.post(
                    "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": token}
                )
            ).status_code == 200

    assert jwks.fetches == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "some-other-application"},
        {"iss": "https://attacker.cloudflareaccess.com"},
        {"exp": int(time.time()) - 60},
    ],
)
async def test_a_jwt_for_something_else_is_refused(
    make_client, monkeypatch, access_settings, claims
):
    key = make_key()
    install_guard(monkeypatch, access_settings, Jwks([jwk_for(key, "kid-1")]))

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush",
            headers={"Cf-Access-Jwt-Assertion": sign(key, "kid-1", **claims)},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_a_jwt_signed_by_another_key_is_refused(
    make_client, monkeypatch, access_settings
):
    published, attacker = make_key(), make_key()
    jwks = Jwks([jwk_for(published, "kid-1")])
    install_guard(monkeypatch, access_settings, jwks)

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush",
            headers={"Cf-Access-Jwt-Assertion": sign(attacker, "kid-1")},
        )

    assert response.status_code == 403


async def test_an_unknown_kid_triggers_exactly_one_refetch(
    make_client, monkeypatch, access_settings
):
    """Access rotates signing keys; one refetch, rate limited, then refuse."""
    key = make_key()
    jwks = Jwks([jwk_for(key, "kid-old")])
    install_guard(monkeypatch, access_settings, jwks)

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush",
            headers={"Cf-Access-Jwt-Assertion": sign(key, "kid-new")},
        )

    assert response.status_code == 403
    assert jwks.fetches == 2


async def test_a_rotated_key_is_picked_up(make_client, monkeypatch, access_settings):
    old, new = make_key(), make_key()
    jwks = Jwks([jwk_for(old, "kid-old")])
    install_guard(monkeypatch, access_settings, jwks)

    async with make_client() as client:
        first = await client.post(
            "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": sign(old, "kid-old")}
        )
        jwks.keys = [jwk_for(new, "kid-new")]
        second = await client.post(
            "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": sign(new, "kid-new")}
        )

    assert (first.status_code, second.status_code) == (200, 200)


async def test_a_malformed_assertion_is_a_403_not_a_500(
    make_client, monkeypatch, access_settings
):
    install_guard(monkeypatch, access_settings, Jwks([]))

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": "not-a-jwt"}
        )

    assert response.status_code == 403


async def test_an_unreachable_jwks_is_a_403_not_a_500(
    make_client, monkeypatch, access_settings
):
    key = make_key()
    install_guard(monkeypatch, access_settings, Jwks([jwk_for(key, "kid-1")], status=502))

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": sign(key, "kid-1")}
        )

    assert response.status_code == 403


async def test_an_assertion_without_access_configured_is_refused(
    make_client, monkeypatch
):
    """No CF_ACCESS_AUD means nothing can be verified, so nothing is trusted."""
    settings = dataclasses.replace(
        main.settings, cf_access_team_domain=None, cf_access_aud=None
    )
    key = make_key()
    install_guard(monkeypatch, settings, Jwks([jwk_for(key, "kid-1")]))

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={"Cf-Access-Jwt-Assertion": sign(key, "kid-1")}
        )

    assert response.status_code == 403
    assert "CF_ACCESS" in response.json()["error"]["message"]


# ---- loopback break-glass ------------------------------------------------


async def test_no_credential_at_all_is_a_403(make_client, monkeypatch, access_settings):
    install_guard(monkeypatch, access_settings, Jwks([]))

    async with make_client() as client:
        response = await client.post("/v1/admin/cache/flush")

    assert response.status_code == 403
    body = response.json()
    assert set(body["error"]) == {"message", "type", "param", "code"}


async def test_the_loopback_token_works_over_ssh(make_client, loopback_admin):
    async with make_client() as client:
        response = await client.post("/v1/admin/cache/flush", headers=loopback_admin)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "hop_header",
    [
        {"Cf-Connecting-Ip": "203.0.113.7"},
        {"Cf-Ray": "8a1b2c3d4e5f6789-LHR"},
        {"X-Forwarded-For": "203.0.113.7"},
    ],
)
async def test_the_loopback_token_is_refused_through_the_tunnel(
    make_client, loopback_admin, hop_header
):
    """cloudflared also connects from 127.0.0.1; the hop headers give it away."""
    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={**loopback_admin, **hop_header}
        )

    assert response.status_code == 403
    assert "loopback-only" in response.json()["error"]["message"]


async def test_a_wrong_loopback_token_is_refused(make_client, loopback_admin):
    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={"X-Admin-Token": "guessed"}
        )

    assert response.status_code == 403


async def test_the_loopback_token_is_ignored_when_unset(make_client, monkeypatch, access_settings):
    install_guard(monkeypatch, access_settings, Jwks([]))

    async with make_client() as client:
        response = await client.post(
            "/v1/admin/cache/flush", headers={"X-Admin-Token": "anything"}
        )

    assert response.status_code == 403


def test_arrived_on_loopback_reads_the_client_and_the_headers():
    class FakeRequest:
        def __init__(self, host, headers):
            self.client = type("C", (), {"host": host})()
            self.headers = headers

    assert arrived_on_loopback(FakeRequest("127.0.0.1", {})) is True
    assert arrived_on_loopback(FakeRequest("::1", {})) is True
    assert arrived_on_loopback(FakeRequest("10.0.0.5", {})) is False
    assert arrived_on_loopback(FakeRequest("127.0.0.1", {"cf-ray": "abc"})) is False


# ---- deep health ---------------------------------------------------------


async def test_deep_health_needs_admin(make_client, monkeypatch, access_settings):
    install_guard(monkeypatch, access_settings, Jwks([]))

    async with make_client() as client:
        response = await client.get("/v1/health/deep")

    assert response.status_code == 403


async def test_deep_health_reports_the_round_trips_health_refuses(
    make_client, loopback_admin, monkeypatch
):
    async def tags():
        return [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]

    monkeypatch.setattr(main.ollama, "tags", tags)

    async with make_client() as client:
        response = await client.get("/v1/health/deep", headers=loopback_admin)

    body = response.json()
    assert response.status_code == 200
    assert body["identity"] == "loopback"
    assert body["neon"]["configured"] is False
    assert body["outbox"]["depth"] == 0
    assert "qwen3.5:9b" in body["models_on_disk"]
    assert "sk-cld" not in json.dumps(body)
