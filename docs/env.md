# Environment variables

Never commit real values. Mini: `~/Cloudiator/.env`, `chmod 600`, kept **outside** the git working tree. Netlify: site env UI. Dashboard must not expose `DATABASE_URL` to the browser.

Template: [.env.example](../.env.example).

## Mini worker — core

| Name | Example | Required |
| --- | --- | --- |
| `CLOUDIATOR_ENV` | `production` | yes |
| `HOST` | `127.0.0.1` | yes |
| `PORT` | `8080` | yes |
| `WEB_CONCURRENCY` | `1` | yes — the worker refuses to boot on any other value |
| `PUBLIC_BASE_URL` | `https://api.example.com` | yes (artifact URLs) |
| `DATABASE_URL` | pooled Neon URL (`...-pooler...`) | yes from Phase B |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | yes |
| `DEFAULT_MODEL` | `gemma4:e4b-it-qat` (or the tag verified in Phase A step 0) | yes |
| `EMBED_MODEL` | `nomic-embed-text` | yes |
| `INFERENCE_BACKEND` | `ollama` | yes — v1. vLLM-metal is not a v1 value |
| `HEAVY_MODEL` | `gpt-oss:20b` | no — **keep commented out until the Phase E pull completes** |
| `VISION_MODEL` | | no — Gemma 4 *is* the VLM. Only set this if the tag gate fell back to a text-only model; it shares slot 1, see `PLAN.md` §7 |
| `GEMMA_THINKING` | `false` | yes — do not enable Gemma thinking mode; Salesforce keys must stay false |
| `NUM_CTX` | `4096` | yes — Gemma's 128K/256K window is not usable on 24GB |
| `MAX_TOKENS_DEFAULT` | `512` | yes |
| `MPLBACKEND` | `Agg` | yes |

`DEFAULT_MODEL` is the single place the model name lives. If Phase A's tag gate picked something other than `gemma4:e4b-it-qat`, change it here and in `docs/operator-checklist.md` §8 — nowhere else. Never point it at `gemma4` / `gemma4:latest` (Q4_K_M ~9.6 GB), `gemma4:*-mlx`, or `gemma4:26b` / `31b`. `INFERENCE_BACKEND=ollama` until a documented v1.1 exclusive vLLM experiment exists (`PLAN.md` §4).

## Mini worker — limits and budgets

These implement the timeout ladder and the tool-loop cap in `PLAN.md` §§9–10. They are not tuning knobs to raise when something times out.

| Name | Default | Purpose |
| --- | --- | --- |
| `MAX_TOOL_ITERATIONS` | `8` | hard cap on the FastAPI-owned tool loop |
| `TOOL_LOOP_BUDGET_SECONDS` | `75` | shared wall clock for the whole loop |
| `SYNC_DEADLINE_SECONDS` | `90` | worker returns its own error before Cloudflare's ~100s 524 |
| `MAX_RESPONSE_BYTES` | `1048576` | response cap for `force_no_stream` keys; Apex heap is ~6 MB |
| `VISION_MAX_EDGE_PX` | `1024` | downscale before the model |
| `VISION_MAX_IMAGES` | `4` | per request |
| `KEY_CACHE_TTL_SECONDS` | `60` | keeps argon2id off the hot path; **revocation lag equals this value** |

## Mini worker — database pool

The Mini holds one process for weeks; Neon computes auto-suspend when idle and drop connections.

| Name | Default | Why |
| --- | --- | --- |
| `DB_POOL_MIN` | `0` | one appliance, one process |
| `DB_POOL_MAX` | `2` | more connections buy nothing and cost Neon quota |
| `DB_CONNECT_TIMEOUT_SECONDS` | `3` | never block a request on a cold compute |
| `DB_STATEMENT_TIMEOUT_SECONDS` | `5` | a slow query must not eat the request budget |
| `DB_POOL_RECYCLE_SECONDS` | `300` | shorter than Neon's idle-suspend window |

Use the **pooled** Neon endpoint (`-pooler` in the hostname). Neon is never on the critical path of a chat: auth falls back to the key cache, usage falls back to the outbox.

## Mini worker — storage

| Name | Example | Notes |
| --- | --- | --- |
| `ARTIFACT_DIR` | `/Users/<you>/Cloudiator/artifacts` | janitor sweeps it every 15 min |
| `ARTIFACT_TTL_HOURS` | `24` | how long the file survives on disk |
| `ARTIFACT_URL_TTL_SECONDS` | `900` | how long a signed URL is valid; re-mint via `POST /v1/artifacts/{id}/sign` |
| `MIN_FREE_DISK_GB` | `10` | below this, refuse generation jobs and report health `degraded`; hard stop at 5 |
| `QUEUE_DB` | `/Users/<you>/Cloudiator/queue.db` | jobs **and** the usage outbox |
| `GEOCODE_CACHE_DB` | `/Users/<you>/Cloudiator/geocode.db` | 30-day TTL; the 1 rps limiter applies to misses only |
| `MFLUX_MODEL_PATH` | `/Users/<you>/Cloudiator/models/flux-schnell-4bit` | always passed explicitly so a request can never trigger a weight download |
| `HF_HOME` | `/Users/<you>/.cache/huggingface` | excluded from Time Machine and Spotlight |

## Mini worker — secrets and admin

| Name | Notes |
| --- | --- |
| `ARTIFACT_SIGNING_SECRET` | 32+ random bytes. Rotating it invalidates every outstanding signed URL |
| `ADMIN_TOKEN` | **loopback-only break-glass.** Accepted only for requests arriving on `127.0.0.1` without traversing the tunnel |
| `CF_ACCESS_TEAM_DOMAIN` | `yourteam.cloudflareaccess.com` — JWKS source for Access JWT validation |
| `CF_ACCESS_AUD` | the Access application's AUD tag; `/v1/admin/*` validates against it |
| `LOG_PROMPTS_DEFAULT` | `false`. Per-key `log_prompts` may not override this upward for Salesforce presets |

Public `/v1/admin/*` is Cloudflare Access + JWT validation, not a bearer token. A token in a header or query string leaks into logs and browser history.

## Mini worker — external services

| Name | Notes |
| --- | --- |
| `NOMINATIM_URL` | `https://nominatim.openstreetmap.org` |
| `NOMINATIM_USER_AGENT` | `Cloudiator/0.1 (real@mailbox)` — **yes, or OSM blocks your home IP**, which takes out everything else on that connection |
| `NOMINATIM_MAX_ROWS_PER_REQUEST` | `25`. Bulk geocoding the public instance is against the usage policy |
| `OVERPASS_URLS` | comma-separated mirrors for failover |
| `OSRM_URL` | `https://router.project-osrm.org` |
| `GOOGLE_MAPS_API_KEY` | optional; requires scope `tools.google_places` **and** accepting Google's ToS |
| `SLACK_WEBHOOK_URL` | optional but strongly recommended — this is how you learn the Mini is down |
| `HF_TOKEN` | optional; FLUX schnell is Apache 2.0 and does not need one |

## Mini worker — renderers

| Name | Default | Notes |
| --- | --- | --- |
| `MPLBACKEND` | `Agg` | never a GUI backend on a headless appliance |
| `ENABLE_MERMAID` | `false` | mermaid-cli ships a headless Chromium at 0.4–1.2 GB resident per render. Graphviz is the default diagram renderer and is the fallback whenever this is off or a render fails |

## Ollama

Ollama's own variables belong on the **Ollama LaunchAgent / app**, not only on FastAPI — the worker cannot set them for a server that is already running. See [host-setup.md](host-setup.md) §5.

`OLLAMA_MAX_LOADED_MODELS=2` with slot 2 reserved for the embedder; `OLLAMA_KEEP_ALIVE=30m` as a safety net while the worker sends an explicit `keep_alive` on every call (`PLAN.md` §4).

## Netlify dashboard

| Name | Purpose |
| --- | --- |
| `DATABASE_URL` | Neon, **server functions only** |
| `ADMIN_SESSION_SECRET` | cookie signing |
| `PUBLIC_API_URL` | `https://api.example.com` shown in snippets |

There is no admin password variable. The dashboard is protected by Cloudflare Access on `app.<domain>`; server functions read `Cf-Access-Authenticated-User-Email` and trust nothing else.

Verify `DATABASE_URL` never reaches the browser: `npm run build && grep -r neon.tech dist/` must find nothing.

## Cloudflare

Tunnel UUID and credentials JSON live in `~/.cloudflared/` on the Mini. Do not put the JSON in git.

## Neon IP

If you enable Neon IP allowlisting, allow **the Mini egress IP** — but a home ISP address rotates, so prefer Neon without an allowlist (SSL-only) unless you have a static egress. Netlify functions also need access.
