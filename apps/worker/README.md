# Cloudiator worker

FastAPI worker for the Mac Mini M4 24GB appliance. Runs **only** on the Mini:
arm64 macOS, Python 3.11, single process, bound to `127.0.0.1:8080`.

See `PLAN.md` §§4, 6, 8, 10 and `docs/cursor-phases.md` Phase A.

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

Tests are hermetic: no Ollama, no network, no macOS-only syscalls.
