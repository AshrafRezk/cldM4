"""Neon operator CLI. Run it on the Mini over SSH, never from a request.

    python -m app.dbtool verify-schema
    python -m app.dbtool apply-schema
    python -m app.dbtool mint-key --tenant acme --name "Salesforce dev"
    python -m app.dbtool revoke-key <public_id>
    python -m app.dbtool list-keys

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

from .auth import (
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    hash_secret,
    mint_secret,
)
from .config import get_settings
from .db import DatabaseUnavailable, Neon, pooled_endpoint
from .openapi_filter import schema_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
NEON_SQL = REPO_ROOT / "infra" / "neon.sql"
DEFAULT_ENV_FILE = Path("~/Cloudiator/.env")


def load_env_file(path: Path) -> list[str]:
    """Fill in variables the shell did not already set. Returns what was loaded.

    The LaunchAgent wrapper sources `~/Cloudiator/.env` for the worker; an
    interactive shell does not, and "DATABASE_URL is not set" about a file that
    plainly sets it is a confusing way to learn the difference. Anything already
    in the environment wins, so a one-off override still works.
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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[name] = value
        loaded.append(name)
    return loaded


def _presets() -> dict[str, Any]:
    path = schema_dir() / "scopes.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text()).get("presets", {})


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
    if not missing:
        print("schema is already applied; nothing to do")
        return 0
    print(f"applying {path} for missing tables: {', '.join(missing)}")
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
    for row in rows:
        state = "revoked" if row["revoked_at"] else "active"
        print(
            f"{row['public_id']}  {state:8}  {row['tenant']:16}  rpm={row['rpm']:<4} "
            f"{row['name']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.dbtool", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-schema", help="report which documented tables are missing")

    apply_cmd = sub.add_parser("apply-schema", help="apply infra/neon.sql if tables are missing")
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

    sub.add_parser("list-keys", help="list keys without secrets")
    return parser


async def _run(args: argparse.Namespace) -> int:
    env_file = Path(os.environ.get("CLOUDIATOR_ENV_FILE") or DEFAULT_ENV_FILE).expanduser()
    if loaded := load_env_file(env_file):
        print(f"read {len(loaded)} variables from {env_file}", file=sys.stderr)
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
