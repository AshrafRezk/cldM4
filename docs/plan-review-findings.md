# Plan review findings (pre-Phase A audit)

Reviewer pass over `PLAN.md`, `README.md`, `AGENTS.md`, `docs/*`, `.cursor/rules/*`, `.env.example`.

**Severity:**

- **P0** — the Mini build stops, the box swaps to death, Salesforce gets HTML instead of JSON, or a security hole ships. Fix before Phase A.
- **P1** — a phase will fail its definition of done, or an operator will burn hours guessing. Fix before the phase that touches it.
- **P2** — quality, cost, or ops hygiene. Fix when convenient.

Every finding below has already been **patched into the instructions**. The "Patched in" column is where the implementer will actually read it. This file is the audit log, not a second source of truth — `PLAN.md` still wins.

---

## P0 — must fix before Phase A

### P0-01 `OLLAMA_MAX_LOADED_MODELS=1` contradicts two always-hot models

`PLAN.md` §4 lists **both** `qwen3.5:9b` and `nomic-embed-text` as "always-hot", then sets `OLLAMA_MAX_LOADED_MODELS=1`. Those cannot both be true. With a limit of 1, every `/v1/embeddings` call evicts the 9B and every following chat pays a 5–15s cold load. An implementer measuring "chat is randomly slow" will chase the wrong bug for a day, or will "fix" it by raising the limit to 4 and putting 9B + 20B in memory at the same time (21 GB → swap → sub-1 tok/s).

**Resolution:** `OLLAMA_MAX_LOADED_MODELS=2`, with a hard product rule that **slot 2 is reserved for `nomic-embed-text` and nothing else**. The "one Metal-heavy model" invariant is enforced by the worker's `metal_lock` + explicit unload, not by the Ollama limit. A startup assertion and a health-check degradation cover the case where the rule is violated.

**Patched in:** `PLAN.md` §4 (Ollama env + slot table), §8 (scheduler rules 0 and 4), `docs/host-setup.md` (Ollama env), `docs/cursor-phases.md` (Phase A DoD wording: at most **one generative** model), `docs/troubleshooting.md`.

### P0-02 `keep_alive=-1` contradicts `OLLAMA_KEEP_ALIVE=30m`

§4 sets the env default to `30m`; §8 says "9B `-1` (forever)". Ollama's env var is only the default for requests that omit `keep_alive`. If the worker omits it, the 9B unloads after 30 minutes of quiet and the next Salesforce call pays a cold load inside a 120s Apex budget.

**Resolution:** both are kept, with the precedence written down. The worker **always sends an explicit `keep_alive`** per request: `-1` for the hot 9B and the embed model, `0` for every exclusive model. `OLLAMA_KEEP_ALIVE=30m` stays as a safety net so a crashed worker cannot pin 14 GB forever.

**Patched in:** `PLAN.md` §4, §8 ("Keep-alive precedence"), `docs/host-setup.md`, `docs/env.md`.

### P0-03 Nothing forbids `uvicorn --workers > 1`

`metal_lock` is an in-process `asyncio.Lock`. Two uvicorn workers means two independent locks, two schedulers, and two processes that each believe they own Metal. The first concurrent FLUX + 20B request kills the box. The plan never said `workers=1`, and the LaunchAgent command omits the flag (relying on an implicit default that an agent may "improve").

**Resolution:** `--workers 1` is now explicit everywhere, with `--reload` and gunicorn banned, plus a startup assertion on `os.environ` / `WEB_CONCURRENCY`.

**Patched in:** `PLAN.md` §6 and §8 (rule 0), `docs/host-setup.md` LaunchAgent + wrapper, `docs/cursor-phases.md` Phase A.

### P0-04 `gpt-oss:20b` is pulled at the wrong time

`PLAN.md` §7 puts `ollama pull gpt-oss:20b` in the same v1 block as the 9B, `docs/host-setup.md` says "Phase E later", and the Phase A prompt says do not pull it. `.env.example` ships `HEAVY_MODEL=gpt-oss:20b` uncommented, so a Phase A `/v1/models` will advertise a model that is not on disk → 404 at call time. The pull is also ~14 GB of disk and 20+ minutes on a home line during Phase A.

**Resolution:** §7 is split into **Phase A set / Phase D2 set / Phase E set / opt-in heavy / never**. `HEAVY_MODEL` is commented out in `.env.example`. `/v1/models` must be built from live `ollama tags`, never from env alone.

**Patched in:** `PLAN.md` §7, `.env.example`, `docs/env.md`, `docs/cursor-phases.md` Phase A + E.

### P0-05 Exclusive slot has no crash path — the 9B never comes back

§8 rule 4 describes the happy path ("load target, run, unload, reload 9B"). If mflux is OOM-killed, raises, or hangs, the lock is held forever and the hot model is gone. Every subsequent Salesforce call gets a 429 until someone reboots the Mini. This is the single most likely way the appliance dies silently at 3am.

**Resolution:** mandatory `try/finally` shape written out as pseudocode: subprocess with a hard timeout, `terminate()` then `kill()` on timeout, reload of the 9B in `finally`, lock released by an `async with`, and a watchdog that re-warms the 9B if `/api/ps` shows no generative model for 60s.

**Patched in:** `PLAN.md` §8 (exclusive slot contract), `docs/cursor-phases.md` Phase E DoD (kill -9 test), `docs/troubleshooting.md`.

### P0-06 Cloudflare Bot Fight Mode will block Salesforce Apex

Apex callouts are non-browser clients: no JavaScript, no cookie jar, no challenge solving. Bot Fight Mode, "I'm Under Attack", Browser Integrity Check, or Turnstile on `api.<domain>` return an HTML interstitial with a 403/503. Apex sees a non-JSON body and throws a parse error that looks nothing like a security block. The plan mentioned a WAF rate limit but never warned about this, and never specified a skip rule.

**Resolution:** explicit zone configuration for `api.<domain>` — Bot Fight Mode **off**, Security Level Essentially Off, Browser Integrity Check off, no Turnstile — plus a WAF custom **Skip** rule keyed on `starts_with(http.request.headers["authorization"][0], "Bearer sk-cld-")`, and rate limiting keyed on the Authorization header rather than IP (Salesforce egress IPs are shared across orgs; IP limiting lets one tenant throttle another).

**Patched in:** `PLAN.md` §13 (new Cloudflare zone settings block), `docs/host-setup.md`, `docs/operator-checklist.md`, `docs/cursor-phases.md` Phase B DoD, `docs/troubleshooting.md`.

### P0-07 SSRF through OpenAI vision `image_url`

The API is OpenAI-compatible, so `messages[].content[].image_url.url` is a caller-supplied URL that the worker will fetch. §12 only scoped SSRF defence to a hypothetical `tools.fetch`. A tenant can point it at `http://169.254.169.254/`, `http://127.0.0.1:11434/`, or any RFC1918 host on the operator's home LAN and read the response back out through the model.

**Resolution:** vision inputs accept `data:` URIs and public `https://` only. DNS is resolved first and every resolved address is checked against loopback, RFC1918, link-local (incl. `169.254.0.0/16`), CGNAT `100.64.0.0/10`, ULA, and multicast; redirects are re-checked; non-`https` schemes, `file://`, and non-image content types are rejected; 25 MB and 10s caps.

**Patched in:** `PLAN.md` §10 (vision input rules) and §12 (SSRF), `docs/cursor-phases.md` Phase A.

### P0-08 FileVault + LaunchAgents means the appliance does not survive a power cut

`docs/licenses.md` says FileVault **must** be on. `PLAN.md` §22 promises "Mini reboot: LaunchAgents bring Ollama, worker, cloudflared back". Both cannot be true unattended: with FileVault on, a cold boot stops at the pre-boot unlock screen. No user session exists, so no LaunchAgent runs, and Ollama.app (a GUI app) cannot start. "Start up automatically after a power failure" gets you to a locked login window and no further.

**Resolution:** the tradeoff is now stated explicitly with three supported options (FileVault + UPS + accept manual unlock; FileVault + `sudo fdesetup authrestart` for planned reboots only; FileVault off with documented physical-security compensation). Auto-login must be enabled for the appliance account, and the recovery runbook is written down. A health webhook covers the "Mini is sitting at the unlock screen" case.

**Patched in:** `PLAN.md` §4 (Power) and §22, `docs/host-setup.md` (FileVault & unattended boot), `docs/operator-checklist.md`, `docs/troubleshooting.md`.

### P0-09 `qwen3.5:9b` is an unverified tag, and the multimodal claim may be wrong

`PLAN.md` §7 pulls `qwen3.5:9b` and §4 calls it "default brain, multimodal, tools". If that exact tag does not exist in the Ollama library on build day, Phase A stops at step 2 with a 404 and an agent will improvise a substitute (possibly a 27B or a non-tool-calling model). Separately, if the chosen tag is a **text** model, the vision path in §9 and §10 has no backing model and Phase D's OCR-first router silently becomes the only image path.

**Resolution:** Phase A now starts with a **model tag verification gate**: resolve the tag, confirm `tools` and (if claimed) `vision` capability, and if it does not resolve, walk a documented fallback ladder and record the decision in `docs/operator-checklist.md`. Vision is explicitly optional in v1 and, if a separate VLM is needed, it occupies the same single generative slot with a documented swap cost — it is not a third hot model.

**Patched in:** `PLAN.md` §7 (tag verification gate + fallback ladder), §4 (slot table), `docs/cursor-phases.md` Phase A step 0, `docs/operator-checklist.md`.

### P0-10 mflux first run downloads ~34 GB inside whatever calls it first

`PLAN.md` §7 shows `mflux-generate --model schnell --quantize 8` as if it were a smoke test. On a clean machine that command downloads the full-precision FLUX.1-schnell repo (transformer + T5 + CLIP + VAE, tens of GB) and then quantizes in memory. Consequences: the first image request blows every HTTP timeout, the 256 GB SSD variant may hit disk-full, and the quantize step repeats on every cold start.

**Resolution:** Phase E gains a mandatory **step 0 offline warmup** run in Terminal, with disk numbers, a preference for a pre-quantized repo, `mflux-save` to a local quantized path under `~/Cloudiator/models/`, an `MFLUX_MODEL_PATH` env var, reclaiming the full-weight cache afterwards, and a hard rule that the worker never triggers a weight download during a request.

**Patched in:** `PLAN.md` §7 (Image) and §4 (Disk), `docs/cursor-phases.md` Phase E, `docs/env.md`, `.env.example`, `docs/operator-checklist.md`.

### P0-11 Nobody owns the tool-calling loop

§9 says chat gets "≤12 tools" but never says who executes them or when the loop stops. Ollama can be asked to handle tools natively; if it does, the worker loses scope enforcement, per-tool timeouts, and usage accounting, and a model that keeps re-calling `geocode` will spin until the Cloudflare 100s origin timeout returns a 524 to Apex.

**Resolution:** FastAPI owns the loop. Hard cap of **8 iterations**, a shared **75s sync wall-clock budget** checked before each iteration, per-tool timeouts, scope check on every call (not just at request start), and a defined stop behaviour when the cap is hit.

**Patched in:** `PLAN.md` §9 (Tool loop contract) and §10 (Timeouts), `docs/cursor-phases.md` Phase D.

### P0-12 Nothing rejects an x86_64 / Rosetta Python

If Terminal or Homebrew was ever installed under Rosetta, `python3.11` is x86_64. `pyobjc-framework-Vision` and `mlx` either fail to install or run translated — Apple Vision OCR and every MLX path silently lose their reason to exist, and the implementer blames the model. The plan pinned the version but never the architecture.

**Resolution:** an architecture gate in `scripts/mac-setup.sh` and in Phase A: `uname -m`, `python -c "import platform; print(platform.machine())"`, and `file $(which python3.11)` must all say `arm64`. Hard abort otherwise, with the "framework build" fallback documented for the pyobjc case.

**Patched in:** `PLAN.md` §5, `docs/host-setup.md` (arm64 gate), `docs/cursor-phases.md` Phase A step 0.

### P0-13 The documented Salesforce job-polling flow is not implementable

`PLAN.md` §3 says "Salesforce Flow polls every 5–10s, max 50 polls" and `docs/salesforce.md` repeats it. 50 polls at 5–10s is 250–500 seconds of wall clock; Apex gives a transaction 120s of cumulative callout time and Flow has no sub-minute sleep. Following this literally produces a Flow that hits the governor limit and fails, in Phase F, in front of a customer org.

**Resolution:** replaced with the three patterns that actually work on the platform — Queueable chaining with a delay, a Scheduled Flow at 1-minute granularity, and a user-driven refresh — each with its own budget note, plus the rule that every poll is its own transaction.

**Patched in:** `PLAN.md` §3 (Jobs flow) and §14, `docs/salesforce.md` (Polling patterns), `docs/cursor-phases.md` Phase F DoD.

---

## P1 — fix before the phase that touches it

### P1-01 Auth ownership is stated three different ways

§2 ("worker validates"), §3 ("add a Worker later only for WAF/bot score"), §6 (`gateway/ # optional Cloudflare Worker, Phase B2`) and §12 ("WAF rate limit"). There is no Phase B2 in `docs/cursor-phases.md`. An agent reading §6 may scaffold a gateway that nothing else references.

**Resolution:** v1 has exactly one authenticator — the FastAPI worker. Cloudflare provides TLS, DDoS, WAF skip, and rate limiting only. `apps/gateway/` is moved to a "do not create in v1" note.

**Patched in:** `PLAN.md` §2, §3, §6, §12.

### P1-02 Chromium-backed renderers are not free, and "tools skip the GPU lock" implies they are

`mmdc` (mermaid-cli) and `kaleido` each launch a headless Chromium: ~150–200 MB on disk, 400 MB–1.2 GB resident per render, and they can spike while the 20B or FLUX owns the exclusive slot. §9's "tools and DuckDB do not take `metal_lock`" is correct about Metal and dangerously wrong about RAM.

**Resolution:** a second, separate `cpu_heavy_lock` (capacity 1) covering Chromium-backed rendering and large DuckDB/OpenCV work, a RAM preflight that refuses when pressure is not `normal` or the exclusive slot is held, Graphviz as the **default** diagram renderer, mermaid behind `ENABLE_MERMAID=false`, and a matplotlib fallback when kaleido is missing.

**Patched in:** `PLAN.md` §8 (second lock), §9 (Family H), `docs/env.md`, `.env.example`, `docs/cursor-phases.md` Phase D3.

### P1-03 Dashboard auth: "shared admin password" vs Cloudflare Access

Phase C offers "simple shared admin password or Netlify Identity"; §12 requires Cloudflare Access. The dashboard mints API keys — a shared password on a public Netlify URL is the weakest link in the whole system, and Netlify Identity is not a sensible choice for new sites.

**Resolution:** Cloudflare Access on `app.<domain>` is mandatory and is the only auth for the dashboard in v1. The app itself holds no login form. `/v1/admin/*` on the worker additionally verifies the `Cf-Access-Jwt-Assertion` JWT against the team JWKS and audience; `ADMIN_TOKEN` survives only as a loopback-only break-glass.

**Patched in:** `PLAN.md` §10, §12, §13, `docs/cursor-phases.md` Phase C, `docs/env.md`, `.env.example`, `docs/operator-checklist.md`.

### P1-04 Neon connection handling is unspecified for a long-lived process

The Mini holds a process for weeks; Neon free/launch computes **auto-suspend after ~5 minutes idle** and drop idle connections. Without a bounded pool and reconnect policy the worker either holds too many connections or hands a dead socket to the auth path and 500s a chat that would otherwise have been served from cache.

**Resolution:** pool min 0 / **max 2**, pre-ping, 300s recycle, 3s connect timeout, 5s statement timeout, pooled (`-pooler`) endpoint, and the rule that **auth falls back to the 60s cache and usage falls back to the outbox** rather than failing a request when Neon is cold. Netlify functions use the Neon serverless HTTP driver, where a short INSERT inside 10s is fine.

**Patched in:** `PLAN.md` §11, `docs/env.md`, `docs/schema.md`, `docs/troubleshooting.md`.

### P1-05 The usage retry queue is named but not specified

§18 says "local queue, retry" with no shape, no cap, and no visibility. An unbounded retry list in memory dies with the process; an unbounded SQLite table fills the disk.

**Resolution:** `usage_outbox` table in the Mini SQLite, flushed every 10s in batches of 500, capped at 100k rows (oldest dropped), never on the request path, depth exposed in `/v1/health`.

**Patched in:** `PLAN.md` §11, `docs/schema.md`, `docs/env.md`.

### P1-06 Neon free tier will fill with raw `usage_events`

Every request writes a row. At a modest few thousand calls a day, raw retention forever is how a free-tier Neon project runs out of storage and starts rejecting writes — which also breaks key minting.

**Resolution:** 30-day retention on raw events plus a `usage_daily` rollup the dashboard reads, and a documented nightly cleanup statement.

**Patched in:** `docs/schema.md`, `PLAN.md` §11.

### P1-07 Cloudflare's 100s origin timeout is the real ceiling, not 120s

§10 lists "chat Salesforce 90s server / 120s client" and §14 says Apex `setTimeout(120000)`. Between them sits Cloudflare's ~100s proxy read timeout (a 524 HTML page, not a JSON error) which is not configurable on the plans this project uses.

**Resolution:** the budget ladder is written as one ordered list — tool timeouts < 75s tool-loop budget < 90s worker hard deadline < ~100s Cloudflare < 120s Apex — with the worker required to return its own OpenAI-shaped timeout error before Cloudflare can produce a 524.

**Patched in:** `PLAN.md` §10 (Timeout ladder), `docs/salesforce.md`, `docs/troubleshooting.md`.

### P1-08 Apex heap/response limits are described but not enforced server-side

"Do not base64 10MB into Apex heap" is advice to the caller. The worker can enforce it.

**Resolution:** `max_response_bytes` (default 1 MB) on keys with `force_no_stream`; OCR/extract results over 500 KB return an artifact URL with a truncated preview; images and PDFs are **always** artifact URLs; a 413-style OpenAI error if the shaped response would exceed the cap.

**Patched in:** `PLAN.md` §10, `docs/salesforce.md`, `docs/schema.md`.

### P1-09 The External Credential failure that costs everyone a day is undocumented

A correctly configured Named Credential + External Credential still returns 401 if the running user's permission set is not granted access to the External Credential **principal**. It presents as "my key works in curl but not in Apex".

**Resolution:** the permission-set step is now a numbered, non-optional step with the exact symptom written next to it.

**Patched in:** `docs/salesforce.md`, `docs/troubleshooting.md`.

### P1-10 External Services cannot import an arbitrary OpenAPI 3.1 document

§10 promises a filtered **OpenAPI 3.1** contract; `docs/salesforce.md` says import it into External Services. Salesforce's importer is conservative: it is happiest with 3.0.x and rejects or mangles several common keywords. Phase F discovers this after the generator is written.

**Resolution:** `GET /v1/openapi.json` keeps 3.1 for generic clients, and `GET /v1/openapi.json?target=salesforce` emits a restricted **3.0.3** document built from a documented safe subset (no `oneOf`/`anyOf`/`allOf`/`not`, no free-form `additionalProperties`, no recursion, no external `$ref`, flat typed objects, unique Apex-safe `operationId`s, no binary/multipart operations). Import is a Phase B smoke test, not a Phase F surprise.

**Patched in:** `PLAN.md` §10, `docs/salesforce.md`, `docs/cursor-phases.md` Phase B + F.

### P1-11 Uploading a file from Apex is treated as a solved problem

`docs/salesforce.md` waves at "multipart from a middleware". Hand-rolling multipart in Apex means blob concatenation through `EncodingUtil` under a 6 MB heap; it is a genuine trap.

**Resolution:** for Salesforce keys, v1 supports JSON row arrays and base64 ≤ 1 MB on `application/json`; multipart is for non-Apex clients only; anything larger is an explicitly out-of-scope integration problem with the options listed.

**Patched in:** `docs/salesforce.md`, `PLAN.md` §10 (Uploads).

### P1-12 Unsupported OpenAI parameters have no defined behaviour

An OpenAI SDK will send `n`, `logprobs`, `seed`, `response_format`, or hit `/v1/files`. Silently ignoring `n=3` and returning one choice is worse than a 400.

**Resolution:** an explicit reject list returning OpenAI-shaped errors, an explicit ignore list, and 404 `not_supported` on the endpoint families that will never exist (assistants, fine-tuning, files, image edits/variations, moderations).

**Patched in:** `PLAN.md` §10 (Parameter support matrix).

### P1-13 Vision images are not downscaled

A 12 MP phone photo pushed straight into a VLM produces thousands of image tokens, silently overflows `num_ctx=4096`, and either truncates the actual question or spikes RAM.

**Resolution:** long edge ≤ 1024 px, JPEG q85, EXIF stripped, max 4 images per request, 25 MB per image, and a pre-flight token estimate that returns `context_length_exceeded` instead of truncating.

**Patched in:** `PLAN.md` §10 (Vision input rules).

### P1-14 Jobs have no idempotency key

Apex retries a callout that timed out. Without idempotency, a retried `POST /v1/jobs` starts a second FLUX generation and the Mini serialises both — the caller waits twice as long and the artifact count doubles.

**Resolution:** optional `Idempotency-Key` header, unique per `key_id` for 24h, returns the original job with `200` instead of creating a new one.

**Patched in:** `PLAN.md` §10, `docs/schema.md` (jobs), `docs/cursor-phases.md` Phase E.

### P1-15 No request correlation id

Three logs (Cloudflare, worker, Neon usage) and no shared key to join them.

**Resolution:** `X-Request-Id` accepted inbound (else generated), returned on **every** response including errors, written to `usage_events.request_id`, and included in the OpenAI error body's `param` when it helps support.

**Patched in:** `PLAN.md` §10, `docs/schema.md`.

### P1-16 `/v1/health` depends on Neon in the obvious implementation

If health does a `SELECT 1` and Neon is suspended, the monitor pages at 3am for a Mini that is perfectly healthy — and the Slack alert in `docs/host-setup.md` fires on it.

**Resolution:** `/v1/health` is local-only, unauthenticated, must return 200 while Neon is down (reporting `"db": "degraded"`), contains no secrets or key hashes, and is rate limited. A separate `/v1/health/deep` behind Cloudflare Access does the round trips.

**Patched in:** `PLAN.md` §10, `docs/host-setup.md`.

### P1-17 argon2id parameters unspecified — and verification cost is on the hot path

"argon2id" without parameters gets whatever the library default is that month. Worse, a correct 64 MiB argon2 verification on **every** request is both slow and a RAM spike next to a 7 GB model.

**Resolution:** OWASP parameters written down (`t=2, m=64 MiB, p=1, hash_len=32, salt_len=16`), plus the rule that the 60s key cache exists **primarily** to keep argon2 off the hot path, keyed on a fast hash of the presented secret with constant-time comparison.

**Patched in:** `PLAN.md` §12, `docs/schema.md`.

### P1-18 Artifact signing: the 15-minute TTL breaks the Salesforce use case it was written for

A Flow polls a job, gets `result.url`, and writes it to a record. Fifteen minutes later the link is dead and the user sees a 404 on a Case they opened the next morning.

**Resolution:** the signing scheme is specified (`HMAC-SHA256(secret, "{id}:{exp}")`, constant-time compare, 404 on bad signature, `nosniff`, no listing, realpath containment inside `ARTIFACT_DIR`), the default TTL is configurable, and `POST /v1/artifacts/{id}/sign` lets a caller re-mint a URL for as long as the artifact survives its retention window. Salesforce guidance is "store the artifact id, not the signed URL".

**Patched in:** `PLAN.md` §10, §12, `docs/salesforce.md`, `docs/env.md`.

### P1-19 DuckDB "allowlist" is a keyword filter, which is not a sandbox

Blocking `COPY`/`INSTALL`/`LOAD` by string matching loses to `read_csv_auto('/etc/passwd')`, `ATTACH`, `PRAGMA`, and comment tricks.

**Resolution:** configuration-level lockdown first (`enable_external_access=false`, `PRAGMA disabled_filesystems='LocalFileSystem'`, `lock_configuration=true`, fresh in-memory connection per request, registered relations only), with the keyword prefilter kept as defence in depth, and worked examples of the attacks it must reject.

**Patched in:** `PLAN.md` §9 (Family D), §12, `docs/cursor-phases.md` Phase D2.

### P1-20 Artifacts and logs grow forever; disk-full has no handler

No TTL, no janitor, no free-space check. `KeepAlive=true` plus `StandardOutPath` is an unbounded log file. A full SSD on the Mini takes down Ollama, the worker, and the tunnel at once.

**Resolution:** `ARTIFACT_TTL_HOURS` (default 24) with a janitor every 15 minutes, `MIN_FREE_DISK_GB` (default 10) below which generation jobs are refused and health goes `degraded`, hard stop at 5 GB, and log rotation via a `newsyslog.d` entry.

**Patched in:** `PLAN.md` §4 (Disk), §10, `docs/host-setup.md`, `docs/env.md`, `.env.example`.

### P1-21 Ollama.app vs `brew install ollama`

Two installs fight over `127.0.0.1:11434`. The loser logs "address already in use", or worse the brew service wins and runs **without** the LaunchAgent env — so `OLLAMA_MAX_LOADED_MODELS` is unset and the 24 GB rule quietly stops applying.

**Resolution:** an explicit conflict check and uninstall step, plus verification that the running server is the one carrying the env.

**Patched in:** `docs/host-setup.md`, `docs/troubleshooting.md`, `docs/cursor-phases.md` Phase A step 0.

### P1-22 `launchctl load` is deprecated and hides failures

`load` is legacy, silently no-ops in several situations, and gives no useful diagnostics. The plist also ships literal `REPLACE` paths that will load "successfully" and then fail to exec.

**Resolution:** `launchctl bootstrap gui/$UID` / `enable` / `kickstart -k` / `print` / `bootout`, plus a path-substitution step and a post-load verification that the port is actually listening.

**Patched in:** `docs/host-setup.md`, `docs/cursor-phases.md` Phase A DoD.

### P1-23 FLUX RAM estimate is optimistic

§4 says "FLUX schnell 4/8-bit, 6–10 GB peak". 8-bit at 1024² on MLX peaks meaningfully higher than 10 GB once the T5 encoder is resident. Budgeting 10 GB and getting 15 is exactly the swap event this plan exists to prevent.

**Resolution:** 4-bit is the documented default for a 24 GB box, 8-bit is opt-in with a measurement requirement, and the peak figure must be recorded during Phase E before the preset is enabled for any key.

**Patched in:** `PLAN.md` §4, §7, `docs/cursor-phases.md` Phase E DoD.

### P1-24 Nominatim rate limiting has no cache, so the 1 rps limiter becomes the bottleneck

A single 1 rps process-wide lock plus a chat tool loop means geocoding a 50-row list takes 50 seconds and blows the sync budget — and repeated identical lookups still count against the policy.

**Resolution:** a persistent geocode cache (SQLite, 30-day TTL), the 1 rps limiter applied only to cache misses, `Retry-After` honoured, batch geocoding explicitly refused above a documented row count with a pointer to self-hosting.

**Patched in:** `PLAN.md` §9 (Family 0), `docs/env.md`, `.env.example`.

### P1-25 `num_ctx` overflow is silent

Ollama drops the oldest tokens when the prompt exceeds the context window. The caller gets a confident answer to a question whose first half was discarded. The plan defines the `context_length_exceeded` error code but never says to raise it.

**Resolution:** estimate prompt tokens before the call; if prompt + `max_tokens` exceeds the key's `max_context`, return `400 context_length_exceeded` rather than letting Ollama truncate.

**Patched in:** `PLAN.md` §10.

### P1-26 macOS Sequoia Local Network permission

On Sequoia, a process first launched by `launchd` can have local network access denied with no prompt anyone will ever see. `cloudflared` and the worker then behave as if the other end is down.

**Resolution:** run each binary **once interactively** in Terminal, approve the prompt, and verify the entry in System Settings → Privacy & Security → Local Network before bootstrapping the LaunchAgent.

**Patched in:** `docs/host-setup.md`, `docs/troubleshooting.md`, `docs/operator-checklist.md`.

### P1-27 Time Machine and Spotlight index the weight caches

`~/.ollama` and `~/.cache/huggingface` are tens of gigabytes of files that change rarely and compress terribly. Time Machine will copy them; `mdworker` will index them. Both produce disk and memory churn at unpredictable times — including in the middle of a generation.

**Resolution:** documented exclusions for `~/.ollama`, `~/.cache/huggingface`, `~/Cloudiator/artifacts`, and `~/Cloudiator/logs`, with the exact `tmutil` and `mdutil` commands.

**Patched in:** `docs/host-setup.md`, `docs/operator-checklist.md`.

### P1-28 Per-key `rpm` exists in the schema with no implementation note

`api_keys.rpm` is defined and never mentioned again. An implementer will either skip it or reach for Redis.

**Resolution:** in-process token bucket per `key_id`, resets on restart (documented as acceptable), returns `429` with `Retry-After`, and is deliberately separate from the Cloudflare rate-limiting rule that fronts it.

**Patched in:** `PLAN.md` §10, §12.

---

## P2 — quality and ops

| ID | Finding | Patched in |
| --- | --- | --- |
| P2-01 | `memory_pressure` needs an implementation note: shelling out every 5s is wasteful and blocks the loop. Use `sysctl -n kern.memorystatus_vm_pressure_level` (1 normal / 2 warn / 4 critical) plus `vm_stat` for free pages, via `asyncio.create_subprocess_exec`, cached. | `PLAN.md` §4, §8 |
| P2-02 | `OLLAMA_ORIGINS` is a browser-CORS setting and provides no authentication. The only protection on 11434 is the loopback bind — any local process or SSH user can drive it. | `PLAN.md` §4, §12 |
| P2-03 | `nomic-embed-text` expects `search_document:` / `search_query:` prefixes for retrieval quality; without them recall degrades quietly. Batch size cap needed. | `PLAN.md` §10 |
| P2-04 | Artifact HMAC expiry depends on a correct clock. Network time must be on. | `docs/host-setup.md` |
| P2-05 | `~/Cloudiator/queue.db` has no backup story; a corrupted SQLite loses queued jobs. | `PLAN.md` §11 |
| P2-06 | `cloudflared` config should pin `protocol: quic` with an http2 fallback note (some ISPs/routers break QUIC UDP) and `no-autoupdate: true` so a self-update does not restart the tunnel mid-job. | `docs/host-setup.md` |
| P2-07 | `.cursor/rules/cloudiator.mdc` did not carry the new hard rules (workers=1, arm64, tool-loop cap, admin behind Access, model pulls are phase-scoped). | `.cursor/rules/cloudiator.mdc` |
| P2-08 | `README.md` document map did not list this file or the operator checklist. | `README.md` |
| P2-09 | Phase prompts said "tests" without naming test files, so tests are the first thing dropped when a phase runs long. | `docs/cursor-phases.md` |
| P2-10 | No rollback instruction per phase; an agent that half-finishes Phase E leaves a broken LaunchAgent and no documented way back. | `docs/cursor-phases.md` |

---

## Explicitly checked and passing (no patch needed)

- Docker is banned for inference in `PLAN.md`, `AGENTS.md`, and `.cursor/rules/cloudiator.mdc` — consistent.
- Netlify is dashboard-only; no inference path touches Functions — consistent across `PLAN.md` §2, §3, §13 and all phase prompts.
- No 70B/120B/default-27B pull appears anywhere; `docs/cursor-phases.md` repeats the ban in its "what not to do" section.
- Video generation is out of v1 in `PLAN.md` header, §2, and §9.
- Unrestricted `eval` is banned in §9 and in the phase prompts.
- Face **recognition** is banned; `tools.face_detect` is detection only and opt-in — correct distinction, left as is.
- Worker binds `127.0.0.1:8080`; port 11434 is never in any ingress block — correct in `PLAN.md` §6, §12, §13 and `docs/host-setup.md`.
- Named tunnel only, quick tunnels rejected — stated in `PLAN.md` §13 step 5 and `docs/host-setup.md`.
- `.gitignore` covers `.env`, `*.pem`, `*.key`, credentials JSON, and artifacts.
- EXIF GPS stripping on by default — `PLAN.md` §9 Family B, §12, and `api_keys.strip_exif`.
- `log_prompts=false` default for Salesforce presets — `PLAN.md` §12, `docs/schema.md`, `docs/salesforce.md`.
- One phase per chat, new chat per phase — consistent in `README.md`, `AGENTS.md`, `docs/cursor-settings.md`, `docs/cursor-phases.md`.
