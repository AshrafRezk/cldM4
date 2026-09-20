# Cloudiator worker

FastAPI worker for the Mac Mini M4 24GB appliance. Runs **only** on the Mini:
arm64 macOS, Python 3.11, single process, bound to `127.0.0.1:8080`.

See `PLAN.md` §§4, 6, 8, 10, 11, 12 and `docs/cursor-phases.md` Phases A and B.

## Layout

| Module | What it owns |
| --- | --- |
| `app/main.py` | routes, the request-id and usage middleware, the auth dependency |
| `app/gates.py` | the boot gates: arm64, Python 3.11, one process, two Ollama slots |
| `app/scheduler.py` | `metal_lock`, `cpu_heavy_lock`, memory-pressure polling, the watchdog |
| `app/ollama.py` | the Ollama client, explicit `keep_alive` on every call |
| `app/auth.py` | `sk-cld-` keys: argon2id, the 60s cache, the per-key rpm bucket |
| `app/db.py` | Neon: pool 0/2, pre-ping, 300s recycle, a breaker so an outage costs no latency |
| `app/usage.py` | the SQLite usage outbox and its background flush |
| `app/admin.py` | Cloudflare Access JWT validation and the loopback break-glass |
| `app/openapi_filter.py` | per-key OpenAPI, built from `packages/schema` |
| `app/dbtool.py` | operator CLI: verify/apply the schema, mint and revoke keys |

Every route but `/v1/health` needs a key. Neon is never on the critical path of a
chat: auth falls back to the 60s key cache and usage falls back to the outbox.

## Run

```bash
cd apps/worker
uv sync --extra dev
export OLLAMA_MAX_LOADED_MODELS=2      # slot 2 is nomic-embed-text only
export WEB_CONCURRENCY=1
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
```

The worker refuses to boot if it is not arm64 macOS on Python 3.11, if
`WEB_CONCURRENCY` is anything but `1`, if `--workers` is not `1`, if
`OLLAMA_MAX_LOADED_MODELS` is not `2`, or if a sibling worker is already
running. Those are the invariants `metal_lock` depends on.

## Test

```bash
cd apps/worker
uv run pytest -q
```

Tests are hermetic: no Ollama, no Neon, no network, no macOS-only syscalls. The
SQLite outbox runs against a temporary file, never `~/Cloudiator/queue.db`.

## Keys

```bash
cd apps/worker
.venv/bin/python -m app.dbtool verify-schema
.venv/bin/python -m app.dbtool mint-key \
  --tenant cloudiator --name 'Salesforce dev' --preset salesforce_engineer
.venv/bin/python -m app.dbtool revoke-key <public_id>
```

The CLI reads `~/Cloudiator/.env` itself (override with `CLOUDIATOR_ENV_FILE`)
for anything the shell has not already set, so there is nothing to source first.
The LaunchAgent wrapper is the only other reader of that file.

The plaintext key is printed **once**; Neon stores an argon2id hash. Revoking
takes up to the 60s key-cache TTL to bite, or `POST /v1/admin/cache/flush` to
make it immediate.
