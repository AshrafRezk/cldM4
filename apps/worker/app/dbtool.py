"""Neon operator CLI. Run it on the Mini over SSH, never from a request.

    python -m app.dbtool verify-schema
    python -m app.dbtool apply-schema
    python -m app.dbtool mint-key --tenant acme --name "Salesforce dev"
    python -m app.dbtool revoke-key <public_id>
    python -m app.dbtool list-keys
    python -m app.dbtool set-capabilities --tenant merck --add voice

Configuration comes from `~/Cloudiator/.env` (override with CLOUDIATOR_ENV_FILE)
unless the variables are already in the environment, so these commands work in a
plain shell without sourcing anything first.

Key minting lives here rather than behind an HTTP route on purpose: in v1 the
only things that mint keys are this CLI and the Phase C dashboard talking to Neon
directly, so there is no mint endpoint on the public surface to protect.

The plaintext key is printed **once**. Neon stores an argon2id hash and nothing
that can reproduce it (PLAN.md §12).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .auth import (
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    KEY_PREFIX,
    PUBLIC_ID_ALPHABET,
    PUBLIC_ID_LENGTH,
    hash_secret,
    mint_secret,
)
from .config import get_settings, reset_settings_cache
from .db import DatabaseUnavailable, Neon, pooled_endpoint
from .openapi_filter import schema_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
NEON_SQL = REPO_ROOT / "infra" / "neon.sql"
DEFAULT_ENV_FILE = Path("~/Cloudiator/.env")


def load_env_file(path: Path) -> list[str]:
    """Fill in variables the shell did not already set. Returns what was loaded.

    The LaunchAgent wrapper reads `~/Cloudiator/.env` for the worker; an
    interactive shell does not, and "DATABASE_URL is not set" about a file that
    plainly sets it is a confusing way to learn the difference. Anything already
    in the environment wins, so a one-off override still works.

    This is a KEY=VALUE parser, not a shell source: unquoted parentheses in
    NOMINATIM_USER_AGENT survive, and `$(...)` is not executed.
    """
    if not path.is_file():
        return []
    loaded: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not name or name in os.environ:
            continue
        if not name.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[name] = value
        loaded.append(name)
    return loaded


def load_catalog() -> dict[str, Any]:
    """Presets and capability names from packages/schema/scopes.json.

    Read on each call so a `git pull` on the Mini is enough. The Console bundles
    this file at deploy time and can lag behind the checkout the Mini is on.
    """
    path = schema_dir() / "scopes.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text())
    return document if isinstance(document, dict) else {}


def _presets() -> dict[str, Any]:
    presets = load_catalog().get("presets") or {}
    return presets if isinstance(presets, dict) else {}


def known_capabilities() -> set[str]:
    raw = load_catalog().get("capabilities") or []
    return {str(item) for item in raw} if isinstance(raw, list) else set()


def capabilities_from_row(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def split_capabilities(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def parse_key_ref(raw: str) -> tuple[str, bool]:
    """Return (public_id, was_full_key). The secret is never part of the result.

    Error text must not echo `raw`: callers paste the whole sk-cld- key.
    """
    text = raw.strip()
    full = False
    if text.startswith(KEY_PREFIX):
        full = True
        public, separator, secret = text[len(KEY_PREFIX) :].partition("_")
        if not separator or not public or not secret:
            raise ValueError("That sk-cld- key is missing the public id or the secret.")
        text = public
    if len(text) != PUBLIC_ID_LENGTH or any(char not in PUBLIC_ID_ALPHABET for char in text):
        raise ValueError(
            "Pass the 12-character public id printed by list-keys. "
            "A full sk-cld- key also works; the secret is not printed or stored again."
        )
    return text, full


def resolve_capabilities(
    current: list[str],
    *,
    preset: str | None = None,
    replace: list[str] | None = None,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> list[str]:
    """The capability list to store. Preset or replace sets the base; add/remove edit it."""
    if preset and replace is not None:
        raise ValueError("Pass either --preset or --capabilities, not both.")
    if preset:
        presets = _presets()
        if preset not in presets:
            known = ", ".join(sorted(presets)) or "(none)"
            raise ValueError(f"unknown preset {preset!r}; known: {known}")
        base = [str(item) for item in presets[preset].get("capabilities") or []]
    elif replace is not None:
        base = list(replace)
    else:
        base = list(current)

    for capability in add or []:
        if capability not in base:
            base.append(capability)
    removed = set(remove or [])
    base = [item for item in base if item not in removed]

    seen: set[str] = set()
    ordered: list[str] = []
    for item in base:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    if not ordered:
        raise ValueError("A key with no capabilities can call nothing.")

    allowed = known_capabilities()
    unknown = [item for item in ordered if item not in allowed]
    if unknown:
        known = ", ".join(sorted(allowed)) or "(catalog is empty — pull the repo)"
        raise ValueError(f"unknown capability {unknown[0]!r}; known: {known}")
    return ordered


def preset_label(capabilities: list[str], preferred: str | None) -> str | None:
    """Preset name when the set matches one. Prefer the name the operator asked for."""
    wanted = set(capabilities)
    matches = [
        name
        for name, spec in _presets().items()
        if set(spec.get("capabilities") or []) == wanted
    ]
    if preferred and preferred in matches:
        return preferred
    if len(matches) == 1:
        return matches[0]
    return None


def format_key_line(row: Any) -> str:
    capabilities = capabilities_from_row(row["capabilities"])
    state = "revoked" if row["revoked_at"] else "active"
    voice = "voice=yes" if "voice" in capabilities else "voice=NO"
    preset = row["preset"] or "custom"
    scopes = ", ".join(capabilities) if capabilities else "(none)"
    head = (
        f"{row['public_id']}  {state:8}  {row['tenant']:16}  rpm={row['rpm']:<4}  "
        f"{voice:9}  {preset:22}  {row['name']}"
    )
    return f"{head}\n    {scopes}"


def flush_local_key_cache(opener=None) -> str:
    """Drop the worker's 60s key cache. The admin token is loopback-only.

    Capability edits are invisible until this runs or the TTL expires. The token
    is sent to 127.0.0.1 and is never included in the message we print.
    """
    settings = get_settings()
    token = settings.admin_token
    if not token:
        return (
            "ADMIN_TOKEN is not set, so the worker cache was not flushed. "
            "The new scopes apply within 60 seconds, or POST "
            "http://127.0.0.1:8080/v1/admin/cache/flush with the loopback admin token."
        )
    url = f"http://127.0.0.1:{settings.port}/v1/admin/cache/flush"
    request = Request(
        url,
        data=b"{}",
        method="POST",
        headers={"X-Admin-Token": token, "Content-Type": "application/json"},
    )

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            raise URLError(f"refused redirect ({code})")

    def _open(req: Request) -> tuple[int, str]:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=3) as response:
            return response.status, response.read().decode("utf-8", "replace")

    try:
        status, body = (opener or _open)(request)
    except HTTPError as exc:
        return (
            f"The worker refused the cache flush ({exc.code}). "
            "The new scopes apply within 60 seconds."
        )
    except URLError as exc:
        return (
            f"Could not reach the worker on 127.0.0.1 to flush the key cache ({exc.reason}). "
            "The new scopes apply within 60 seconds."
        )
    except OSError as exc:
        return (
            f"Could not reach the worker on 127.0.0.1 to flush the key cache ({exc}). "
            "The new scopes apply within 60 seconds."
        )
    if token in body:
        body = body.replace(token, "[redacted]")
    return f"Worker key cache flushed ({status}): {body.strip()}"


async def _verify_schema(db: Neon) -> int:
    missing = await db.missing_tables()
    if missing:
        print(f"missing tables: {', '.join(missing)}")
        print("apply them with: python -m app.dbtool apply-schema")
        return 1
    print("schema present: tenants, api_keys, usage_events, usage_daily, jobs")
    return 0


async def _apply_schema(db: Neon, path: Path) -> int:
    """Idempotent: every statement in infra/neon.sql is IF NOT EXISTS."""
    missing = await db.missing_tables()
    if missing:
        print(f"applying {path} for missing tables: {', '.join(missing)}")
    else:
        print(f"tables present; re-applying {path} for added columns (idempotent)")
    await db.execute_script(path.read_text())
    still_missing = await db.missing_tables()
    if still_missing:
        print(f"still missing after apply: {', '.join(still_missing)}")
        return 1
    print("schema applied")
    return 0


async def _mint_key(db: Neon, args: argparse.Namespace) -> int:
    preset = None
    capabilities = [c.strip() for c in (args.capabilities or "").split(",") if c.strip()]
    max_tokens, max_context, force_no_stream = args.max_tokens, args.max_context, args.no_stream
    max_response_bytes = args.max_response_bytes

    if args.preset:
        presets = _presets()
        if args.preset not in presets:
            print(f"unknown preset {args.preset!r}; known: {', '.join(sorted(presets))}")
            return 2
        preset = args.preset
        spec = presets[preset]
        capabilities = capabilities or list(spec.get("capabilities", []))
        max_tokens = max_tokens or spec.get("max_tokens")
        max_context = max_context or spec.get("max_context")
        force_no_stream = force_no_stream or bool(spec.get("force_no_stream"))
        max_response_bytes = max_response_bytes or spec.get("max_response_bytes")

    if not capabilities:
        print("a key with no capabilities can call nothing; pass --preset or --capabilities")
        return 2

    public_id, secret, plaintext = mint_secret()
    secret_hash = hash_secret(secret)

    async def action(con):
        tenant_id = await con.fetchval(
            """
            INSERT INTO tenants (slug, name) VALUES ($1, $2)
            ON CONFLICT (slug) DO UPDATE SET name = tenants.name
            RETURNING id
            """,
            args.tenant,
            args.tenant_name or args.tenant,
        )
        return await con.fetchval(
            """
            INSERT INTO api_keys (
              tenant_id, public_id, secret_hash, name, preset, capabilities, models,
              tools, max_tokens, max_context, rpm, force_no_stream, max_response_bytes
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13)
            RETURNING id
            """,
            tenant_id,
            public_id,
            secret_hash,
            args.name,
            preset,
            json.dumps(capabilities),
            json.dumps([m.strip() for m in (args.models or "").split(",") if m.strip()]),
            json.dumps([t.strip() for t in (args.tools or "").split(",") if t.strip()]),
            max_tokens or 512,
            max_context or 4096,
            args.rpm,
            force_no_stream,
            max_response_bytes or 1_048_576,
        )

    key_id = await db.run(action, statement_timeout_seconds=15.0)
    print(f"key_id     {key_id}")
    print(f"public_id  {public_id}")
    print(f"tenant     {args.tenant}")
    print(f"scopes     {', '.join(capabilities)}")
    if "voice" not in capabilities:
        print("voice      NO  (/v1/voice will return 403 until this key has voice)")
    else:
        print("voice      yes")
    print(f"rpm        {args.rpm}")
    print()
    print("Shown once. Store it in the password manager, not in git:")
    print(f"  {plaintext}")
    print()
    print("Revoking it takes up to the key cache TTL (60s) to take effect, or call")
    print("POST /v1/admin/cache/flush to make it immediate.")
    return 0


async def _revoke_key(db: Neon, public_id: str) -> int:
    async def action(con):
        return await con.fetchval(
            "UPDATE api_keys SET revoked_at = now() WHERE public_id = $1 AND revoked_at IS NULL "
            "RETURNING id",
            public_id,
        )

    key_id = await db.run(action, statement_timeout_seconds=15.0)
    if key_id is None:
        print(f"no active key with public_id {public_id!r}")
        return 1
    print(f"revoked {key_id}")
    print("Flush the worker key cache to make it immediate: POST /v1/admin/cache/flush")
    return 0


async def _list_keys(db: Neon) -> int:
    async def action(con):
        return await con.fetch(
            """
            SELECT k.public_id, k.name, t.slug AS tenant, k.preset, k.rpm, k.revoked_at,
                   k.capabilities
            FROM api_keys k JOIN tenants t ON t.id = k.tenant_id
            ORDER BY k.created_at DESC
            """
        )

    rows = await db.run(action, statement_timeout_seconds=15.0)
    if not rows:
        print("no keys")
        return 0
    missing: list[str] = []
    for row in rows:
        print(format_key_line(row))
        if not row["revoked_at"] and "voice" not in capabilities_from_row(row["capabilities"]):
            missing.append(str(row["public_id"]))
    if missing:
        print()
        print("These active keys have no voice scope, so /v1/voice returns 403:")
        print("  " + ", ".join(missing))
        print("Add it without changing the secret Salesforce already has:")
        print("  python -m app.dbtool set-capabilities --add voice <public_id>")
        print("  python -m app.dbtool set-capabilities --tenant <slug> --add voice")
    return 0


_VOICE_PROOF = (
    'curl -s -o /dev/null -w \'%{http_code}\\n\' '
    '"$API/v1/voice/scripts" -H "Authorization: Bearer $KEY"'
)


async def _set_capabilities(db: Neon, args: argparse.Namespace) -> int:
    """Change scopes on a key that already exists. The secret stays the same."""
    if not args.key and not args.tenant:
        print("Pass a public_id, or --tenant to update every active key on that tenant.")
        return 2
    if args.preset and args.capabilities:
        print("Pass either --preset or --capabilities, not both.")
        return 2
    if not any((args.preset, args.capabilities, args.add, args.remove)):
        print("Pass --preset, --capabilities, --add, or --remove.")
        return 2

    public_id: str | None = None
    if args.key:
        try:
            public_id, full = parse_key_ref(args.key)
        except ValueError as exc:
            print(exc)
            return 2
        if full:
            print(
                "The full key was on the command line, so it is in your shell history. "
                "Next time pass only the public id from list-keys. "
                "The secret was not printed or stored again.",
                file=sys.stderr,
            )

    tenant = args.tenant.strip().lower() if args.tenant else None
    replace = split_capabilities(args.capabilities) if args.capabilities else None
    add = split_capabilities(args.add)
    remove = split_capabilities(args.remove)

    class _WriteAbort(Exception):
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

    async def action(con):
        if public_id:
            rows = await con.fetch(
                """
                SELECT k.public_id, k.name, k.preset, k.capabilities, k.revoked_at,
                       t.slug AS tenant
                FROM api_keys k
                JOIN tenants t ON t.id = k.tenant_id
                WHERE k.public_id = $1
                  AND ($2::text IS NULL OR lower(t.slug) = $2)
                """,
                public_id,
                tenant,
            )
        else:
            rows = await con.fetch(
                """
                SELECT k.public_id, k.name, k.preset, k.capabilities, k.revoked_at,
                       t.slug AS tenant
                FROM api_keys k
                JOIN tenants t ON t.id = k.tenant_id
                WHERE lower(t.slug) = $1
                  AND t.deleted_at IS NULL
                  AND k.revoked_at IS NULL
                ORDER BY k.created_at
                """,
                tenant,
            )
        if not rows:
            return {"error": "missing"}
        planned: list[dict[str, Any]] = []
        for row in rows:
            if row["revoked_at"]:
                return {"error": "revoked", "public_id": row["public_id"]}
            current = capabilities_from_row(row["capabilities"])
            try:
                updated = resolve_capabilities(
                    current,
                    preset=args.preset,
                    replace=replace,
                    add=add,
                    remove=remove,
                )
            except ValueError as exc:
                return {"error": "bad", "public_id": row["public_id"], "message": str(exc)}
            label = preset_label(updated, args.preset or row["preset"])
            planned.append(
                {
                    "public_id": row["public_id"],
                    "capabilities": updated,
                    "preset": label,
                    "unchanged": updated == current and label == row["preset"],
                }
            )
        written = []
        for item in planned:
            saved = await con.fetchrow(
                """
                UPDATE api_keys
                SET capabilities = $1::jsonb,
                    preset = $2
                WHERE public_id = $3
                  AND revoked_at IS NULL
                RETURNING public_id, name, preset, capabilities
                """,
                json.dumps(item["capabilities"]),
                item["preset"],
                item["public_id"],
            )
            if saved is None:
                raise _WriteAbort({"error": "revoked", "public_id": item["public_id"]})
            written.append({**dict(saved), "unchanged": item["unchanged"]})
        return {"error": None, "written": written}

    try:
        result = await db.run(action, statement_timeout_seconds=15.0)
    except _WriteAbort as exc:
        result = exc.payload
    except ValueError as exc:
        print(exc)
        return 2

    if result["error"] == "missing":
        if public_id and tenant:
            print(f"no key {public_id} on tenant {tenant}")
        elif public_id:
            print(f"no key with public_id {public_id}")
        else:
            print(f"no active keys on tenant {tenant}")
        return 1
    if result["error"] == "revoked":
        print(f"{result['public_id']} is revoked. Mint a new key; revoked secrets cannot be re-scoped.")
        return 1
    if result["error"] == "bad":
        print(f"{result['public_id']}: {result['message']}")
        return 2

    for row in result["written"]:
        capabilities = capabilities_from_row(row["capabilities"])
        voice = "voice=yes" if "voice" in capabilities else "voice=NO"
        note = " (unchanged)" if row["unchanged"] else ""
        preset = row["preset"] or "custom"
        print(f"{row['public_id']}  {row['name']}  preset={preset}  {voice}{note}")
        print(f"    {', '.join(capabilities)}")
    print()
    print(
        "The secret did not change. The key already stored in Salesforce "
        "(Setup → CloudiatorPrincipal → ApiKey) is still the right one."
    )
    print(flush_local_key_cache())
    print()
    print("Prove voice. Expect 200. Take KEY from the password manager; do not paste it into chat.")
    print("  export API=https://api.cloudiator.org")
    print(f"  {_VOICE_PROOF}")
    if any("voice" not in capabilities_from_row(row["capabilities"]) for row in result["written"]):
        print("voice is still off on at least one key. /v1/voice will keep returning 403.")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.dbtool", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-schema", help="report which documented tables are missing")

    apply_cmd = sub.add_parser("apply-schema", help="apply infra/neon.sql (idempotent; also adds new columns)")
    apply_cmd.add_argument("--file", default=str(NEON_SQL))

    mint = sub.add_parser("mint-key", help="mint an sk-cld- key and print it once")
    mint.add_argument("--tenant", required=True, help="tenant slug")
    mint.add_argument("--tenant-name")
    mint.add_argument("--name", required=True, help="human label for the key")
    mint.add_argument("--preset", help="preset from packages/schema/scopes.json")
    mint.add_argument("--capabilities", help="comma separated, overrides the preset list")
    mint.add_argument("--models", help="comma separated; empty means the default model only")
    mint.add_argument("--tools", help="comma separated chat tool names (max 12)")
    mint.add_argument("--max-tokens", type=int)
    mint.add_argument("--max-context", type=int)
    mint.add_argument("--max-response-bytes", type=int)
    mint.add_argument("--rpm", type=int, default=30)
    mint.add_argument(
        "--no-stream", action="store_true", help="force stream=false (Salesforce keys)"
    )

    revoke = sub.add_parser("revoke-key", help="revoke by public_id")
    revoke.add_argument("public_id")

    sub.add_parser("list-keys", help="list keys without secrets, and flag any that lack voice")

    edit = sub.add_parser(
        "set-capabilities",
        help="add or replace scopes on an existing key; the secret stays the same",
    )
    edit.add_argument(
        "key",
        nargs="?",
        help="public_id, or a full sk-cld- key (the secret is not printed or stored again)",
    )
    edit.add_argument("--tenant", help="update every active key on this tenant slug, for example merck")
    edit.add_argument("--preset", help="replace scopes with this preset from packages/schema/scopes.json")
    edit.add_argument("--capabilities", help="comma separated replacement list")
    edit.add_argument("--add", help="comma separated scopes to add, for example voice")
    edit.add_argument("--remove", help="comma separated scopes to remove")
    return parser


async def _run(args: argparse.Namespace) -> int:
    env_file = Path(os.environ.get("CLOUDIATOR_ENV_FILE") or DEFAULT_ENV_FILE).expanduser()
    if loaded := load_env_file(env_file):
        print(f"read {len(loaded)} variables from {env_file}", file=sys.stderr)
        reset_settings_cache()
    settings = get_settings()
    if not settings.database_url:
        print(
            f"DATABASE_URL is not set, and {env_file} does not set it either. "
            "It belongs in that file (chmod 600, outside git).",
            file=sys.stderr,
        )
        return 2
    if not pooled_endpoint(settings.database_url):
        print(
            "warning: DATABASE_URL is not the pooled Neon endpoint (no '-pooler' in the host)",
            file=sys.stderr,
        )
    db = Neon(settings)
    try:
        if args.command == "verify-schema":
            return await _verify_schema(db)
        if args.command == "apply-schema":
            return await _apply_schema(db, Path(args.file))
        if args.command == "mint-key":
            return await _mint_key(db, args)
        if args.command == "revoke-key":
            return await _revoke_key(db, args.public_id)
        if args.command == "list-keys":
            return await _list_keys(db)
        if args.command == "set-capabilities":
            return await _set_capabilities(db, args)
    except DatabaseUnavailable as exc:
        print(f"Neon is unreachable: {exc}", file=sys.stderr)
        return 3
    finally:
        await db.close()
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "mint-key":
        print(
            f"argon2id t={ARGON2_TIME_COST} m={ARGON2_MEMORY_COST}KiB p={ARGON2_PARALLELISM} "
            "(PLAN.md §12)",
            file=sys.stderr,
        )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
