# Next steps — Phase D3 proven (2026-09-27)

**Phases A–D3 are proven on the Mini.** Phase D is [PR #11](https://github.com/AshrafRezk/cldM4/pull/11). Phase D2 is [PR #12](https://github.com/AshrafRezk/cldM4/pull/12). Phase D3 is [PR #13](https://github.com/AshrafRezk/cldM4/pull/13). Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Phase E starts with a human disk check and an offline FLUX warmup. Do not `ollama pull gpt-oss:20b` until that warmup is recorded.

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md).

## Done

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. Chat from the Air returned JSON 200. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords.

**Mini `.env`:** `NOMINATIM_USER_AGENT` is quoted. `DEFAULT_MODEL=gemma4:e4b-it-qat`. KEY=VALUE `.env` loader (do not `source` the file). `PUBLIC_BASE_URL=https://api.cloudiator.org` derives playground CORS as `https://app.cloudiator.org`.

**Dashboard (Phase C, live):** `https://app.cloudiator.org` on Netlify, Cloudflare Access only (no login form, no shared password). Landing at `/` (Agentforce-native product page + logo). Operator console at `/console` (tenants, scoped keys shown once, usage_daily, Salesforce OAS + Apex `setTimeout(120000)` / `"stream": false`, browser playground → Mini). `DATABASE_URL` is server-side only; `cd apps/dashboard && npm test` finds no `neon.tech` in `dist/`.

## Phase D proof (Mini, 2026-09-27)

| Check | Result |
| --- | --- |
| OCR `POST /v1/tools/ocr` on a large-font PNG | `{"text":"INVOICE 42"}` HTTP 200. No extra model loaded (`idle_hot_9b`). |
| Geocode `Cairo, Egypt` | `30.0443879, 31.2357257`. Second call `0.005s` (SQLite cache). |
| Chat-only key, `POST /v1/tools/ocr` | 403 |
| Signed artifact URL | 200 |
| Tampered signature | 404 |
| Path traversal | 404 |

`ocrmac` is installed in the worker venv (`uv pip`, not a `pip` binary). OCR passes a PIL image. `ARTIFACT_SIGNING_SECRET` is in `~/Cloudiator/.env`.

## Phase D2 proof (Mini, 2026-09-27)

The first `kickstart` returned before port 8080 was listening. After the worker logged `Application startup complete`, health stayed `idle_hot_9b`.

| Check | Result |
| --- | --- |
| `POST /v1/tools/query` fruit CSV, `SUM` by kind | `apples/5`, `pears/4`, `truncated: false` |
| `POST /v1/tools/chart` | `engine: matplotlib`, signed PNG URL on `https://api.cloudiator.org/artifacts/...` |
| Loaded models | `gemma4:e4b-it-qat`, `nomic-embed-text`. Swap 0. |

matplotlib, numpy, scipy, duckdb, and pyarrow are installed in the worker venv with `uv pip`.

## Phase D3 proof (Mini, 2026-09-27)

The first diagram call returned `not_supported`. Terminal had `/opt/homebrew/bin/dot`; the LaunchAgent PATH did not. The renderer now checks that path. After `git pull` and `kickstart`, health stayed `idle_hot_9b` with 388.4 GB free.

| Check | Result |
| --- | --- |
| `POST /v1/tools/text` `sf_id` `001D000000IRt53` | `001D000000IRt53IAD` |
| `POST /v1/tools/diagram` with `engine: mermaid` | `engine: graphviz`, signed PNG URL |
| Loaded models | `gemma4:e4b-it-qat`, `nomic-embed-text`. Swap 0. `dot` is `/opt/homebrew/bin/dot`. |

## Next

Merge [PR #11](https://github.com/AshrafRezk/cldM4/pull/11), then [#12](https://github.com/AshrafRezk/cldM4/pull/12), then [#13](https://github.com/AshrafRezk/cldM4/pull/13), in that order, when `main` should match the Mini.

Phase E is the following phase. Its first step is a human warmup in Terminal, not a worker change and not an `ollama pull`. Record peak memory and wall clock in [operator-checklist.md](operator-checklist.md) section 9 before any job-queue code. Skip `gpt-oss:20b` unless `df -h /` still shows comfortable headroom after the 4-bit weights are on disk. 4-bit is the default. Do not quantize to 8-bit in the same sitting.

Run this on the Mini. It downloads the pre-quantized 4-bit weights (~7 GB) into `~/Cloudiator/models`, stops the worker so Gemma is not resident during the generate, then starts the worker again. Leave `-q` and `--model schnell` off this command. Those pull the full-precision repo (~34 GB) and quantize it in memory.

```bash
df -h /
export PATH="$HOME/.local/bin:$PATH"
launchctl bootout "gui/$(id -u)/ai.cloudiator.worker" || true
ollama stop gemma4:e4b-it-qat || true
uv tool install --upgrade mflux
mkdir -p ~/Cloudiator/models
uvx --from huggingface_hub hf download dhairyashil/FLUX.1-schnell-mflux-v0.6.2-4bit \
  --local-dir ~/Cloudiator/models/flux-schnell-4bit
du -sh ~/Cloudiator/models/flux-schnell-4bit
time mflux-generate --path ~/Cloudiator/models/flux-schnell-4bit \
  --steps 4 --height 1024 --width 1024 \
  --prompt "a red bicycle" --output /tmp/test.png
sysctl vm.swapusage
ls -lh /tmp/test.png
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/ai.cloudiator.worker.plist"
launchctl kickstart -k "gui/$(id -u)/ai.cloudiator.worker"
```

Paste `df`, the `time` real line, `vm.swapusage`, and the size of `/tmp/test.png`. If generate reports that the saved weights are incompatible with this mflux, stop there and paste the error. The fallback is one local `mflux-save --quantize 4`, then deleting the full-precision Hugging Face cache.

## Remaining

| When | What | Where |
| --- | --- | --- |
| When you want `main` to match the Mini | Merge PR #11, then #12, then #13 | GitHub, then Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| Phase E, after the warmup above is recorded | Exclusive-slot image jobs. `gpt-oss:20b` only if disk still allows | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
