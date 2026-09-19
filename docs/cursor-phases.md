# Cursor phase prompts (Mac Mini)

Full picker / Privacy / spend-cap setup: **[cursor-settings.md](cursor-settings.md)**.
Findings this file was patched against: **[plan-review-findings.md](plan-review-findings.md)**.
Operator inputs that must be filled before Phase B: **[operator-checklist.md](operator-checklist.md)**.

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

Every phase below has four parts and none of them are optional:

- **Prompt** — paste this, nothing else.
- **Files that must exist after** — if one is missing, the phase is not done.
- **Prove it** — commands with expected output. Run them yourself; do not accept the agent's word.
- **Rollback** — how to get back to the previous green phase when the agent half-finishes.

---

## Phase 0 — operator inputs (human, no agent)

Not a Cursor phase. First complete [hardware-and-network.md](hardware-and-network.md) (desk, Ethernet, CGNAT, no WAN forwards). Then fill in [operator-checklist.md](operator-checklist.md) sections 1–6 before Phase B, and section 0 before Phase A.

**Prove it:** [hardware-and-network.md](hardware-and-network.md) §9 sign-off is ticked; no blanks in operator-checklist §§1–5; exactly one boot policy ticked in §6; you can explain what Bot Fight Mode does to a Salesforce callout.

---

## Phase A — Local OpenAI shim + RAM lock

**Model: Claude Opus 5.**

```
Phase A only.

STEP 0 — gates. Do these before writing any application code, and stop if one fails.
a) Architecture: uname -m, python3.11 -c "import platform;print(platform.machine())", and file $(which python3.11) must all be arm64. Abort on x86_64 (PLAN.md section 5).
b) Ollama conflict: `brew list ollama` must be empty. If not, brew uninstall it. Only the official Ollama.app may own 127.0.0.1:11434.
c) Model tag gate (PLAN.md section 7): ollama pull gemma4:e4b-it-qat && ollama show gemma4:e4b-it-qat. Confirm **tools and vision**, and that the quant is QAT Q4_0 (~6 GB), not gemma4:latest (~9.6 GB Q4_K_M). Then smoke Arabic: ollama run gemma4:e4b-it-qat "اكتب جملة واحدة بالفصحى عن الطقس اليوم." Expect Arabic back. If the tag does not resolve, walk the documented fallback ladder, then tell me which model you chose and stop for confirmation before continuing. Do NOT pull gemma4:26b, gemma4:31b, *-q8_0, or *-bf16.
d) Smoke-test Apple Vision early even though OCR is Phase D: python -c "import Vision" in the venv. If it fails with a framework error, rebuild the venv against /opt/homebrew/opt/python@3.11/bin/python3.11.

1. Create apps/worker as FastAPI + uv + Python 3.11. Commit .python-version (3.11) and uv.lock. uv python pin 3.11.
2. scripts/mac-setup.sh: the arm64 gate from step 0, brew deps from docs/host-setup.md, Time Machine and Spotlight exclusions, newsyslog log rotation, then ollama pull for the DEFAULT model (`gemma4:e4b-it-qat`) and nomic-embed-text only (llama3.2:3b optional). Do NOT pull gpt-oss:20b, gemma4:26b, gemma4:31b, Q8/bf16 Gemma, 27B, 70B, or 120B in this phase.
3. Implement:
   - GET /v1/health — unauthenticated, local-only, no Neon call, no secrets. Returns ok, free_mb, loaded, queue_depth, pressure, free_disk_gb, db, version.
   - POST /v1/chat/completions (OpenAI JSON in/out, call Ollama 127.0.0.1:11434)
   - POST /v1/embeddings
   - GET /v1/models — built from live `ollama tags`, never from env
   - metal_lock (single asyncio.Lock) and the state machine from PLAN.md section 8
   - cpu_heavy_lock as a separate semaphore, capacity 1
   - memory pressure poller: sysctl -n kern.memorystatus_vm_pressure_level every 5s via asyncio.create_subprocess_exec, cached, off the request path
   - X-Request-Id on every response including errors
   - num_ctx default 4096, max_tokens default 512, and a pre-flight token estimate that returns 400 context_length_exceeded instead of letting Ollama silently truncate
   - Explicit keep_alive on every Ollama call: -1 for the hot model and the embedder, 0 for anything else (PLAN.md section 4). GEMMA_THINKING=false; do not inject thinking tokens.
   - The unsupported-parameter matrix from PLAN.md section 10 (reject n>1, logprobs, top_logprobs, best_of, logit_bias)
   - SSRF guard for vision image_url inputs: https and data: only, DNS-resolve and reject private ranges, re-check redirects, downscale to 1024px long edge, max 4 images
4. Bind 127.0.0.1:8080 only, uvicorn --workers 1. Assert single-process at startup and refuse to boot if WEB_CONCURRENCY is anything but 1. No --reload in the LaunchAgent.
5. LaunchAgent plist for the worker using launchctl bootstrap gui/$UID (not launchctl load). Substitute real paths for REPLACE. Document the Ollama env from PLAN.md section 4, including OLLAMA_MAX_LOADED_MODELS=2 with slot 2 reserved for nomic-embed-text.
6. Tests as files, not a manual session:
   - apps/worker/tests/test_openai_translation.py
   - apps/worker/tests/test_metal_lock.py (lock is released when the body raises)
   - apps/worker/tests/test_ssrf_guard.py (169.254.169.254, 127.0.0.1, 10.x, file://, http:// all rejected)
   - apps/worker/tests/test_context_guard.py
   - scripts/smoke-phase-a.sh
```

**Files that must exist after:** `apps/worker/app/main.py`, `apps/worker/pyproject.toml`, `uv.lock`, `.python-version`, `scripts/mac-setup.sh`, `scripts/smoke-phase-a.sh`, `~/Library/LaunchAgents/ai.cloudiator.worker.plist`, the four test files above.

**Prove it:**

```bash
uname -m                                          # arm64
apps/worker/.venv/bin/python -c "import platform;print(platform.machine())"   # arm64
pgrep -fc "uvicorn app.main:app"                  # exactly 1
lsof -nP -iTCP:8080 -sTCP:LISTEN                  # bound to 127.0.0.1, NOT *:8080
curl -s http://127.0.0.1:8080/v1/health | jq      # ok=true, no secrets, no key hashes
curl -sD- -o/dev/null http://127.0.0.1:8080/v1/health | grep -i x-request-id
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"'"$DEFAULT_MODEL"'","messages":[{"role":"user","content":"say hi"}],"max_tokens":16}' | jq .choices[0].message
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"'"$DEFAULT_MODEL"'","messages":[{"role":"user","content":"اكتب جملة واحدة بالفصحى عن الطقس."}],"max_tokens":64}' | jq .choices[0].message
# Arabic completion must contain Arabic letters, not an English apology
ollama ps                                         # at most ONE generative model (+ nomic-embed-text)
sysctl vm.swapusage                               # used = 0.00M
cd apps/worker && .venv/bin/pytest -q             # green
launchctl print gui/$UID/ai.cloudiator.worker | head -20   # state = running
```

`ollama ps` showing two *generative* models is a phase failure, not a warning. `nomic-embed-text` alongside one generative model is expected and correct.

**Rollback:** `launchctl bootout gui/$UID/ai.cloudiator.worker`, `git checkout -- apps/worker scripts`, `rm -rf apps/worker/.venv`. Models stay on disk; nothing else in this phase touches state outside the repo.

---

## Phase B — Neon keys + Cloudflare Tunnel

**Model: Claude Opus 5.**

Do not start this phase until [operator-checklist.md](operator-checklist.md) §§1–5 have no blanks.

```
Phase B only. Do not start the dashboard UI except a stub if needed.

1. Apply docs/schema.md to Neon. Put the POOLED DATABASE_URL in the Mini .env (chmod 600, never commit).
2. Neon client config per PLAN.md section 11: pool min 0 / max 2, pre-ping, 300s recycle, 3s connect timeout, 5s statement timeout. Neon must never be on the critical path of a chat response.
3. API keys: mint sk-cld-{public_id}_{secret}, argon2id with time_cost=2, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16. Look up by public_id, constant-time verify. 401/403/429 in OpenAI error shape.
4. Cache key lookups 60s (positive and negative) so argon2id is off the hot path. Add POST /v1/admin/cache/flush. Strip Authorization from every log path including exception handlers.
5. Per-key rpm token bucket in-process, 429 + Retry-After.
6. usage_outbox in the Mini SQLite: write locally, flush to Neon every 10s in batches of 500, cap 100k rows dropping oldest, expose outbox_depth in /v1/health. A chat must succeed with Neon completely down.
7. Named Cloudflare Tunnel to http://127.0.0.1:8080 only, config from docs/host-setup.md, no-autoupdate true. No quick tunnels. 11434 must never appear in the ingress.
8. GET /v1/openapi.json filtered by key scopes, plus ?target=salesforce emitting the restricted OpenAPI 3.0.3 subset from PLAN.md section 10.
9. /v1/admin/* verifies the Cf-Access-Jwt-Assertion JWT against the Access JWKS and CF_ACCESS_AUD. ADMIN_TOKEN is accepted only for requests arriving on loopback.
10. Tests: apps/worker/tests/test_auth.py, test_key_cache.py, test_usage_outbox.py, test_openapi_filter.py, scripts/smoke-phase-b.sh.
```

**Files that must exist after:** `infra/neon.sql`, `apps/worker/app/auth.py`, `apps/worker/app/usage.py`, `packages/schema/*`, `~/.cloudflared/config.yml`, `~/Library/LaunchAgents/com.cloudiator.cloudflared.plist`, the four test files, `scripts/smoke-phase-b.sh`.

**Prove it** — the first four from a **phone on cellular**, not the Mini's wifi:

```bash
# 1. real key over HTTPS
curl -s https://api.<domain>/v1/chat/completions -H "Authorization: Bearer $REAL_KEY" \
  -H 'content-type: application/json' \
  -d '{"model":"'"$DEFAULT_MODEL"'","messages":[{"role":"user","content":"hi"}],"stream":false,"max_tokens":16}' | jq

# 2. bad key must be a JSON 401 from FastAPI, NOT a Cloudflare HTML page
curl -s -o /tmp/bad.txt -w '%{http_code}\n' https://api.<domain>/v1/chat/completions \
  -H "Authorization: Bearer sk-cld-nope_nope" -H 'content-type: application/json' -d '{}'
head -c 200 /tmp/bad.txt     # must start with {"error": ... — if it is <!DOCTYPE html, the WAF is eating you

# 3. WAF skip proven with a non-browser client
curl -s -A 'Salesforce/1.0' -o /dev/null -w '%{http_code}\n' https://api.<domain>/v1/health   # 200

# 4. Ollama is not reachable from the WAN
curl -s --max-time 5 https://api.<domain>:11434/api/tags ; echo "exit=$?"    # must fail
grep -c 11434 ~/.cloudflared/config.yml                                      # must be 0

# 5. Neon down drill (on the Mini)
#    block Neon at the firewall or use a bad host, then:
curl -s http://127.0.0.1:8080/v1/chat/completions ... | jq     # still 200 on a cached key
curl -s http://127.0.0.1:8080/v1/health | jq '.db, .outbox_depth'   # "degraded", depth > 0
#    restore Neon, wait 15s, depth returns to 0 and rows appear in usage_events

# 6. Salesforce OAS import
curl -s "https://api.<domain>/v1/openapi.json?target=salesforce" -H "Authorization: Bearer $REAL_KEY" -o /tmp/oas.json
jq '.openapi' /tmp/oas.json                                     # "3.0.3"
jq '[.. | objects | select(has("oneOf") or has("anyOf") or has("allOf"))] | length' /tmp/oas.json   # 0
# then actually import /tmp/oas.json into External Services in a dev org. It must import clean.
```

**Rollback:** `cloudflared tunnel delete cloudiator-mini` and remove the DNS record; `launchctl bootout` the cloudflared agent; revoke any minted keys in Neon (`UPDATE api_keys SET revoked_at = now()`); the Phase A loopback worker keeps working untouched.

---

## Phase C — Netlify dashboard

**Model: Claude Sonnet 5.**

```
Phase C only.

1. apps/dashboard Vite React. NO login form, NO shared admin password, NO Netlify Identity. Authentication is Cloudflare Access on app.<domain>, configured outside the app. The app reads the Cf-Access-Authenticated-User-Email header in its server functions and trusts nothing else.
2. Create tenant, mint key, checkboxes for scopes from PLAN.md section 9 presets.
3. Show the key once. Next to the revoke button, state plainly that revocation takes up to 60 seconds to propagate (worker key cache).
4. Usage chart from Neon, reading the usage_daily rollup rather than raw events.
5. Download OpenAPI JSON for that key, with a separate "Salesforce (External Services)" button that hits ?target=salesforce.
6. Copy-paste Salesforce Named Credential + Apex snippet from docs/salesforce.md. The snippet must contain req.setTimeout(120000) and "stream": false.
7. Netlify deploy. DATABASE_URL is server-side only. No inference in Netlify functions, ever.
8. Tests: a build-output check that greps dist/ for neon.tech and fails if found.
```

**Files that must exist after:** `apps/dashboard/`, `apps/dashboard/netlify/functions/*`, `apps/dashboard/package-lock.json`, the build-output secret check in CI or `package.json` scripts.

**Prove it:**

```bash
cd apps/dashboard && npm run build
grep -r "neon.tech" dist/ ; echo "exit=$? (1 = good, nothing found)"
```

- Incognito window on `app.<domain>` is challenged by **Cloudflare Access**, not a password form.
- Mint a Salesforce-engineer key, download both OAS variants, run one chat with the key, and see a usage row appear.
- The Apex snippet on screen contains `setTimeout(120000)`.

**Rollback:** unpublish/delete the Netlify site, `git checkout -- apps/dashboard`. Neon rows stay; revoke any test keys.

---

## Phase D — Tool registry + OCR + maps

**Model: Claude Opus 5.**

```
Phase D only.

Implement the tool registry skeleton (PLAN.md section 9): folder per tool, schema.json, REST route, artifact store, gpu:false, per-tool timeout, golden fixture test.

The tool loop is FastAPI's, not Ollama's (PLAN.md section 9, "Tool loop contract"):
- max 8 iterations
- 75s shared wall-clock budget, checked before each iteration
- scope re-checked on EVERY tool call, not once per request
- break immediately on an identical repeated tool call
- on cap, return finish_reason "stop" plus x-cloudiator-tool-iterations

Ship:
- POST /v1/tools/ocr (Apple Vision / ocrmac)
- geocode, places, route (Nominatim with User-Agent from env, a persistent SQLite geocode cache with 30-day TTL, a process-wide 1 rps limiter applied to cache MISSES only, Retry-After honoured, Overpass failover, OSRM)
- Refuse bulk geocode above 25 rows per request
- Chat tools ocr_image, geocode, places_nearby
- Scope enforcement with 403 scope_denied
- Artifact signing per PLAN.md section 12: HMAC-SHA256, constant-time compare, 404 on bad signature, realpath containment, nosniff
- POST /v1/artifacts/{id}/sign
- Artifact janitor every 15 min honouring ARTIFACT_TTL_HOURS, and MIN_FREE_DISK_GB refusal

Tests: tests/test_tool_loop_cap.py, tests/test_scope_enforcement.py, tests/test_geocode_cache.py, tests/test_artifact_signing.py (expired, tampered, traversal).
```

**Files that must exist after:** `apps/worker/tools/<id>/handler.py` + `schema.json` per tool, `apps/worker/app/tool_loop.py`, `apps/worker/app/artifacts.py`, the four test files.

**Prove it:**

```bash
# OCR loads no extra weights
ollama ps > /tmp/before.txt
curl -s -F file=@screenshot.png http://127.0.0.1:8080/v1/tools/ocr -H "Authorization: Bearer $KEY" | jq .text
ollama ps > /tmp/after.txt && diff /tmp/before.txt /tmp/after.txt   # no change

# Nominatim User-Agent is real, and the cache works
curl -s http://127.0.0.1:8080/v1/tools/geocode -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' -d '{"q":"Cairo, Egypt"}' | jq
# repeat the same call: second one returns in <50ms and makes no outbound request

# unscoped key
curl -s -o/dev/null -w '%{http_code}\n' http://127.0.0.1:8080/v1/tools/ocr -H "Authorization: Bearer $NO_OCR_KEY"   # 403

# artifact signing
curl -s -o/dev/null -w '%{http_code}\n' "$SIGNED_URL"                     # 200
curl -s -o/dev/null -w '%{http_code}\n' "${SIGNED_URL}x"                  # 404, not 403
curl -s -o/dev/null -w '%{http_code}\n' "$BASE/artifacts/../../.env?..."  # 404
```

**Rollback:** `git checkout -- apps/worker/tools apps/worker/app`, restart the worker. Delete `~/Cloudiator/artifacts/*` and the geocode cache if they are in a bad state — both are regenerable.

---

## Phase D2 — Charts, stats, DuckDB

**Model: Claude Sonnet 5.**

```
Phase D2 only.

- POST /v1/tools/chart (matplotlib default; plotly/kaleido only behind cpu_heavy_lock, with matplotlib fallback; a missing or crashed kaleido must never fail worker import or the request)
- POST /v1/tools/stats (describe, ttest, ols, monte_carlo, npv — PLAN.md Family C)
- POST /v1/tools/query — DuckDB, locked down by CONFIGURATION first per PLAN.md Family D:
    fresh in-memory connection per request,
    SET enable_external_access=false; SET disabled_filesystems='LocalFileSystem'; SET lock_configuration=true;
    caller data registered as an in-memory relation only,
    keyword prefilter as defence in depth, single statement only
- Chat tools render_chart, stats_describe, sql_on_table
- MPLBACKEND=Agg
- Caps: 30s SQL, 10k rows preview, parquet artifact if larger

Tests: tests/test_duckdb_sandbox.py must include every rejected statement listed in PLAN.md Family D and assert each is refused. tests/test_chart_fallback.py must pass with kaleido uninstalled.
```

**Prove it:**

```bash
.venv/bin/pytest tests/test_duckdb_sandbox.py -q            # all reject cases green
.venv/bin/pip uninstall -y kaleido && .venv/bin/pytest tests/test_chart_fallback.py -q
# CSV -> group by -> chart
curl -s -X POST http://127.0.0.1:8080/v1/tools/query -H "Authorization: Bearer $KEY" ... | jq
curl -s -X POST http://127.0.0.1:8080/v1/tools/chart -H "Authorization: Bearer $KEY" ... | jq -r .url
# open that URL: PNG renders. ollama ps unchanged throughout (the numeric path uses no model).
```

**Rollback:** `git checkout -- apps/worker/tools`, restart. No persistent state beyond artifacts.

---

## Phase D3 — Image ops, docs, diagrams, utilities

**Model: Grok 4.6 (or Claude Sonnet 5).**

```
Phase D3 only. Do not add FLUX.

Pillow/HEIC/OpenCV-headless (headless wheel only)/QR/EXIF (strip GPS by default)/palette; pypdf/pdfplumber/docx/xlsx extract; fpdf2/openpyxl render; rapidfuzz; phonenumbers; pint; holidays; Salesforce 15/18 Ids.

Diagrams: Graphviz is the DEFAULT renderer. mermaid-cli is opt-in behind ENABLE_MERMAID=false, takes cpu_heavy_lock, runs with --no-sandbox --single-process --disable-dev-shm-usage, has a 30s timeout, kills its process tree on timeout, and falls back to Graphviz on any failure. Do not make mermaid a required dependency.

Large extractions return an artifact URL plus a truncated preview rather than a multi-megabyte JSON body (max_response_bytes).

Tests: tests/test_heic.py, tests/test_qr_roundtrip.py, tests/test_pdf_extract.py, tests/test_sf_ids.py, tests/test_diagram_fallback.py (mermaid disabled still renders via Graphviz).
```

**Prove it:** HEIC from a real iPhone photo converts; QR encodes and decodes; PDF text extracts; `ENABLE_MERMAID=false` still returns a diagram via Graphviz; a 15-char Id converts to 18 and round-trips. During a mermaid render (if enabled), Activity Monitor shows the Chromium process and it **exits** afterwards — no orphans.

**Rollback:** `git checkout -- apps/worker/tools`. If mermaid-cli misbehaves: `npm -g uninstall @mermaid-js/mermaid-cli` and set `ENABLE_MERMAID=false`; nothing else depends on it.

---

## Phase E — FLUX + jobs

**Model: Claude Opus 5.**

```
Phase E only.

STEP 0 — offline warmup, run by the human in Terminal, NOT by the worker (PLAN.md section 7):
  df -h /                       # need the headroom before you start
  uv tool install --upgrade mflux
  obtain pre-quantized 4-bit weights, or mflux-save --model schnell --quantize 4 --path ~/Cloudiator/models/flux-schnell-4bit
  time mflux-generate --path ~/Cloudiator/models/flux-schnell-4bit --steps 4 --height 1024 --width 1024 --prompt "a red bicycle" --output /tmp/test.png
  record peak memory and wall clock in docs/operator-checklist.md section 9
  reclaim the full-precision HF cache if you took the quantize-locally path
Do not write code that can trigger a weight download during an HTTP request. 4-bit is the default; 8-bit only after measuring with zero swap.

1. mflux exclusive slot via MFLUX_MODEL_PATH, always passed explicitly.
2. The exclusive slot contract from PLAN.md section 8, exactly: async with metal_lock, unload hot model, poll /api/ps until only nomic-embed-text remains, run with a hard timeout, and in `finally` kill orphan subprocesses (terminate then kill), unload, and reload the hot model best-effort.
3. Watchdog task every 30s: if no generative model is loaded and no exclusive job is running for 60 consecutive seconds, re-warm the hot model.
4. POST /v1/jobs + GET /v1/jobs/{id}. SQLite queue at QUEUE_DB so jobs survive a restart. Idempotency-Key header, unique per key_id for 24h, returns the original job.
5. Salesforce keys cannot sync-wait FLUX — images are always a job for them.
6. Signed artifact URLs per PLAN.md section 12, and POST /v1/artifacts/{id}/sign for re-minting.
7. Optionally pull gpt-oss:20b now (~14GB) if disk allows; it uses the same exclusive slot. Still never gemma4:26b / 31b / 27B / 70B / 120B.
8. Tests: tests/test_exclusive_teardown.py (the run raises -> lock released AND hot model reloaded), tests/test_job_idempotency.py, tests/test_job_restart.py (queued job survives a worker restart).
```

**Files that must exist after:** `apps/worker/app/jobs.py`, `apps/worker/app/scheduler.py` (or equivalent), `apps/worker/tools/image_generate/`, `~/Cloudiator/models/flux-schnell-4bit/`, the three test files.

**Prove it — including the crash drill, which is the point of this phase:**

```bash
# happy path
JOB=$(curl -s -X POST http://127.0.0.1:8080/v1/jobs -H "Authorization: Bearer $KEY" \
  -H 'Idempotency-Key: test-1' -H 'content-type: application/json' \
  -d '{"kind":"image","prompt":"a red bicycle"}' | jq -r .id)
curl -s -X POST http://127.0.0.1:8080/v1/jobs -H "Authorization: Bearer $KEY" -H 'Idempotency-Key: test-1' ... | jq -r .id   # SAME id
watch -n5 "curl -s http://127.0.0.1:8080/v1/jobs/$JOB | jq .status"      # succeeded
sysctl vm.swapusage                                                       # used = 0.00M
ollama ps                                                                 # hot model back, one generative

# CRASH DRILL — start another image job, then:
pkill -9 -f mflux
sleep 60
curl -s http://127.0.0.1:8080/v1/chat/completions ... | jq .choices[0].message   # must work, no human intervention
ollama ps                                                                        # hot model reloaded by the watchdog

# restart drill
launchctl kickstart -k gui/$UID/ai.cloudiator.worker
curl -s http://127.0.0.1:8080/v1/jobs/$JOB | jq .status                          # job still there
```

**Rollback:** `launchctl bootout` the worker, `git checkout -- apps/worker`, `rm ~/Cloudiator/queue.db` (loses queued jobs only). Weights under `~/Cloudiator/models/` are expensive to re-download — keep them. If `gpt-oss:20b` was pulled and disk is tight, `ollama rm gpt-oss:20b` and comment `HEAVY_MODEL` back out.

---

## Phase F — Salesforce pack + optional Whisper

**Model: Claude Sonnet 5.**

```
Phase F only.

1. docs/salesforce.md: Named Credential + External Credential, INCLUDING the permission set that grants the running user the External Credential principal (without it the callout 401s while curl works).
2. External Services import using GET /v1/openapi.json?target=salesforce (OpenAPI 3.0.3 restricted subset).
3. Apex examples with req.setTimeout(120000) and "stream": false.
4. Job polling: implement and document ONE of the three patterns in docs/salesforce.md. Each poll is its own transaction. Do not write a loop of 50 callouts inside one Apex execution — that exceeds the 120s cumulative callout budget.
5. Salesforce keys: force stream=false with the x-cloudiator-stream-downgraded header, max_response_bytes 1MB, artifact ids rather than signed URLs stored on records.
6. Optional mlx-whisper large-v3-turbo exclusive slot + /v1/audio/transcriptions, using the same exclusive slot contract and try/finally teardown as FLUX.

Tests: tests/test_sf_stream_downgrade.py, tests/test_response_size_cap.py.
```

**Prove it:** a real callout from a dev org using the dashboard snippet returns chat JSON in under 120s; the OAS imports into External Services without errors; a poll pattern retrieves a finished job across separate transactions; a deliberately oversized response returns an artifact URL rather than blowing Apex heap.

**Rollback:** delete the External Service and Named Credential in the org; revoke that org's key; `git checkout -- docs apps/worker`.

---

## What not to do in any phase

- `ollama pull` 70B / 120B / default 27B / `gemma4:26b*` / `gemma4:31b*` / Gemma Q8 or bf16 as the hot model
- `ollama pull gpt-oss:20b` before Phase E
- `uvicorn --workers` anything other than 1; no gunicorn; no `--reload` in a LaunchAgent
- `OLLAMA_MAX_LOADED_MODELS` anything other than 2, and slot 2 is `nomic-embed-text` only
- Let Ollama run the tool loop
- Docker Desktop for inference
- Netlify functions calling Ollama
- Unrestricted Python `eval`
- Face recognition (detection is a separate, opt-in scope)
- Video models
- A shared admin password or a login form in the dashboard
- Scaffolding `apps/gateway/` — not in v1
- Committing `.env`
