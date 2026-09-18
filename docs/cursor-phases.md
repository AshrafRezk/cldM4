# Cursor phase prompts (Mac Mini)

Full picker / Privacy / spend-cap setup: **[cursor-settings.md](cursor-settings.md)**.

Use a **new Agent chat per phase**. Set **Agent** mode. **Auto off.** Attach `@PLAN.md` `@docs/cursor-phases.md`. First message of every chat:

```
You are implementing Cloudiator from this repo. Read PLAN.md, docs/cursor-settings.md, and the docs/ files. Do not skip RAM rules. Do not use Docker for Ollama. Do not put inference in Netlify. Work only on the current phase. Commit when the phase definition of done is met if I ask you to commit.
```

Then paste the phase block.

| Phase | Model dropdown |
| --- | --- |
| A, B, D, E | Claude Opus 5 (latest Opus) |
| C, D2, F | Claude Sonnet 5 (latest Sonnet) |
| D3 and bugfixes | Grok 4.6 or Composer 2.5 |

---

## Phase A — Local OpenAI shim + RAM lock

**Model: Claude Opus 5.**

```
Phase A only.

1. Create apps/worker as FastAPI + uv + Python 3.11 venv.
2. scripts/mac-setup.sh: brew deps from docs/host-setup.md, ollama pull qwen3.5:9b and nomic-embed-text (llama3.2:3b optional). Do not pull 27B or 120B.
3. Implement:
   - GET /v1/health
   - POST /v1/chat/completions (OpenAI JSON in/out, stream optional, call Ollama 127.0.0.1:11434)
   - POST /v1/embeddings
   - GET /v1/models
   - metal_lock + OLLAMA_MAX_LOADED_MODELS=1
   - num_ctx default 4096, max_tokens default 512
4. Bind 127.0.0.1:8080 only.
5. LaunchAgent plist for worker and document Ollama env from PLAN.md.
6. Tests: pytest for JSON translation; a script that curls loopback.

Definition of done: curl chat on loopback returns a completion; ollama ps shows at most one model; health reports free_mb and loaded model.
```

---

## Phase B — Neon keys + Cloudflare Tunnel

**Model: Claude Opus 5.**

```
Phase B only. Do not start the dashboard UI except a stub if needed.

1. Apply docs/schema.md to Neon. Put DATABASE_URL in Mini .env (never commit).
2. API keys: mint sk-cld-, argon2id hash, scopes JSON, 401/403/429.
3. Cache key lookup 60s. Strip Authorization from logs.
4. Named Cloudflare Tunnel to http://127.0.0.1:8080 only. Config from docs/host-setup.md. No quick tunnels. Never expose 11434.
5. GET /v1/openapi.json filtered by key scopes (even if only chat/embeddings exist yet).
6. Usage insert async; local retry queue if Neon fails.
7. 503 mini_offline is for the future worker watchdog; for now health is local.

Definition of done: from a device that is not the Mini, HTTPS chat with a real key works; bad key is 401; Ollama port is not reachable from WAN.
```

---

## Phase C — Netlify dashboard

**Model: Claude Sonnet 5.**

```
Phase C only.

1. apps/dashboard Vite React: login (simple shared admin password or Netlify Identity).
2. Create tenant, mint key, checkboxes for scopes from PLAN.md presets.
3. Show key once. Usage chart from Neon.
4. Download OpenAPI JSON for that key.
5. Copy-paste Salesforce Named Credential + Apex snippet (120000 timeout) from docs/salesforce.md.
6. Netlify deploy. No inference in Netlify functions.

Definition of done: I can mint a Salesforce-engineer key, download OAS, see a usage row after one chat.
```

---

## Phase D — Tool registry + OCR + maps

**Model: Claude Opus 5.**

```
Phase D only.

Implement the tool registry skeleton (PLAN.md section 9): folder per tool, schema.json, REST, OpenAI tools on chat, artifact store, gpu:false.

Ship:
- POST /v1/tools/ocr (Apple Vision / ocrmac)
- geocode, places, route (Nominatim User-Agent + 1 rps, Overpass failover, OSRM)
- Chat tools ocr_image, geocode, places_nearby
- Scope enforcement

Definition of done: OCR a screenshot without loading extra weights; geocode works with proper User-Agent; unscoped key gets 403.
```

---

## Phase D2 — Charts, stats, DuckDB

**Model: Claude Sonnet 5.**

```
Phase D2 only.

- POST /v1/tools/chart (matplotlib default, plotly/kaleido if available, matplotlib fallback)
- POST /v1/tools/stats (describe, ttest, ols, monte_carlo, npv — PLAN.md Family C)
- POST /v1/tools/query DuckDB read-only SQL allowlist
- Chat tools render_chart, stats_describe, sql_on_table
- MPLBACKEND=Agg
- Caps: 30s SQL, 10k rows preview

Definition of done: CSV in → SQL group by → PNG chart URL. LLM is not used for the numeric path when hitting /v1/tools/*.
```

---

## Phase D3 — Image ops, docs, diagrams, utilities

**Model: Grok 4.6 (or Claude Sonnet 5).**

```
Phase D3 only. Do not add FLUX.

Pillow/HEIC/OpenCV-headless/QR/EXIF/palette; pypdf/pdfplumber/docx/xlsx extract; fpdf2/openpyxl render; mermaid-cli + graphviz; rapidfuzz; phonenumbers; pint; holidays; Salesforce 15/18 IDs.

Definition of done: HEIC converts; QR encode/decode; PDF text extract; mermaid → SVG; 15-char Id converts to 18.
```

---

## Phase E — FLUX + jobs

**Model: Claude Opus 5.**

```
Phase E only.

mflux FLUX.1-schnell quantized exclusive slot. Unload 9B, generate, reload 9B.
POST /v1/jobs + GET /v1/jobs/{id}. SQLite queue on Mini. Salesforce keys cannot sync-wait FLUX.
Signed artifact URLs 15 min.

Definition of done: image job succeeds; memory_pressure normal afterwards; 9B answers chat again without manual restart.
```

---

## Phase F — Salesforce pack + optional Whisper

**Model: Claude Sonnet 5.**

```
Phase F only.

docs/salesforce.md: Named Credential, External Services import, Apex examples, Flow poller for jobs.
Optional mlx-whisper large-v3-turbo exclusive slot + /v1/audio/transcriptions.

Definition of done: a Salesforce callout using the dashboard snippet returns chat JSON; a Flow can poll a job.
```

---

## What not to do in any phase

- `ollama pull` 70B / 120B / default 27B
- Docker Desktop for inference
- Netlify functions calling Ollama
- Unrestricted Python eval
- Face recognition
- Video models
- Committing `.env`
