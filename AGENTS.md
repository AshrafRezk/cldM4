# Agent notes

Read `PLAN.md`, `docs/hardware-and-network.md`, and `docs/cursor-settings.md` before generating code. `docs/plan-review-findings.md` explains why the harder constraints exist.

- Mac Mini M4 24GB appliance. One Metal model at a time.
- Execute only the current phase from `docs/cursor-phases.md`. Each phase lists files, proof commands, and rollback.
- `uvicorn --workers 1`. `OLLAMA_MAX_LOADED_MODELS=2` (slot 2 is the embedder only). Explicit `keep_alive` on every call.
- Python 3.11 arm64 only; abort on Rosetta.
- FastAPI owns the tool loop: 8 iterations, 75s budget.
- No Docker for inference. No Netlify inference. No 70B/120B/`gemma4:26b`/`gemma4:31b` pulls. Default chat is `gemma4:e4b-it-qat`. `gpt-oss:20b` is Phase E only.
- Cloudflare Access for admin and dashboard; no shared password.
- Libraries first, models last. Do not commit secrets.
