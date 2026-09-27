# Next steps — finish v1 (2026-09-27)

**Phases A–E are proven on the Mini at `cde136e`.** Live check the same day: `HEAD` `cde136e`, state `idle_hot_9b`, loaded `gemma4:e4b-it-qat` + `nomic-embed-text`, and `POST` to `/v1/tools/ocr`, `/v1/tools/geocode`, `/v1/jobs`, and `/v1/chat/completions` all returned **401**. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not pull `gpt-oss:20b`. Do not run FLUX 8-bit.

Repo on the Mini: `/Users/ashrafrezk/cldM4`  
Env (outside git, `chmod 600`): `/Users/ashrafrezk/Cloudiator/.env`  
Secrets stay in the password manager, not this file. Blanks: [operator-checklist.md](operator-checklist.md).

v1 is finished when every box in [Finish line](#finish-line) is checked. Work top to bottom. Steps 1–4 are operator actions on the Mini, Neon, Netlify, and Cloudflare. Step 5 is the only remaining code phase.

## Proven — do not redo

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords. Playground CORS allows `https://app.cloudiator.org`.

**Dashboard:** `https://app.cloudiator.org` on Netlify, Cloudflare Access only. Landing at `/`. Operator console at `/console`. `DATABASE_URL` is server-side only.

**Phase D (Mini):** OCR on a large-font PNG returned `INVOICE 42` with no extra model. Geocode `Cairo, Egypt` was `30.0443879, 31.2357257`; the repeat was `0.005s` from the SQLite cache. A chat-only key got 403 on OCR. Signed / tampered / traversal artifact URLs were 200 / 404 / 404.

**Phase D2 (Mini):** Fruit CSV query grouped to apples 5 and pears 4. Chart returned a matplotlib PNG. Hot model stayed loaded.

**Phase D3 (Mini):** `sf_id` `001D000000IRt53` became `001D000000IRt53IAD`. A mermaid request rendered with Graphviz (`/opt/homebrew/bin/dot`). Hot model stayed loaded.

**Phase E (Mini):** Job `dcbfbc7dc5af4e7e91967a7e5c057496` succeeded with artifact `8034c949723d4c1caca9c7838abfbb06` on 4-bit schnell `--low-ram` (peak 8.43 GB MLX, wall clock 1:56). Killing `mflux-generate` mid-job (`1bf553e4641a47f29159da6f307e2317`) left chat working (`Hi.`), Gemma reloaded, and the failed job still present after `kickstart`. Weights: `/Users/ashrafrezk/Cloudiator/models/flux-schnell-4bit`.

`/v1/health` reporting `db: "unknown"` is expected. That route does not call Neon.

## Finish line

- [ ] **1. Reboot clears leftover swap** so `/v1/health` returns `"ok": true` and `swap_used_mb` is 0.
- [ ] **2. Playground chat** from `https://app.cloudiator.org/console` returns JSON and a `usage_daily` row appears.
- [ ] **3. `infra/neon-retention.sql` is scheduled** (Neon). Raw `usage_events` older than 30 days get deleted.
- [ ] **4. `cloudiator.netlify.app` is disabled.** Only `https://app.cloudiator.org` serves the dashboard.
- [ ] **5. Phase F** — Salesforce stream downgrade and 1 MB cap in the worker, then a real External Services import and Apex callout.
- [ ] **6. Unattended boot** — one FileVault policy in operator-checklist §6, auto-login, no computer sleep, and a tested health alert.

Explicitly **not** required to finish v1: `gpt-oss:20b`, FLUX 8-bit, mlx-whisper, vLLM-metal, a Cloudflare Worker, `apps/gateway/`.

---

## 1. Clear leftover swap (Mini)

The 19.08 GB FLUX run (no `--low-ram`) left swap in use. The later `--low-ram` job did not add any. At 17:42 UTC on 2026-09-27 health was:

```json
{"ok": false, "state": "idle_hot_9b", "swap_used_mb": 1611.88, "degraded": ["swap_in_use"], "free_disk_gb": 375.3, "pressure": "normal"}
```

FileVault policy is still unticked (§6). A reboot stops at the unlock screen until someone types the password. After login, LaunchAgents must be running again.

```bash
cd /Users/ashrafrezk/cldM4
# reboot from the Apple menu, unlock, log in as ashrafrezk, then:
launchctl print gui/$UID/ai.cloudiator.worker | head -5
/usr/bin/curl -s http://127.0.0.1:8080/v1/health | /usr/bin/python3 -m json.tool
```

Expect `"ok": true`, `"degraded": []`, `swap_used_mb` 0, `state` `idle_hot_9b`, and both models loaded. If `ok` is still false, read `degraded` before changing models.

## 2. Playground usage row

Open `https://app.cloudiator.org/console` (Cloudflare Access, no password form). Send one playground chat with a real key. The response is JSON. In Neon, a row for today exists in `usage_daily` for that key. The dashboard usage chart reads the rollup, not raw `usage_events`.

## 3. Schedule Neon retention

Free-tier storage fills if raw `usage_events` are kept forever, and then **key minting fails**. The statement is `infra/neon-retention.sql` (same SQL as [schema.md](schema.md)). Run it once in the Neon SQL editor to confirm it succeeds, then schedule it nightly (Neon scheduled job). Tick operator-checklist §3 when the schedule exists.

Do not point the worker at this query. `/v1/health` must stay off Neon.

## 4. Disable the Netlify default hostname

The site also answers on `https://cloudiator.netlify.app`. Turn that hostname off in Netlify (Domain management) so the only public dashboard is `https://app.cloudiator.org`, which is the hostname behind Cloudflare Access. Confirm an incognito window on `app.cloudiator.org` is an Access challenge, and that `cloudiator.netlify.app` no longer serves the app.

## 5. Phase F — Salesforce pack

Docs for the org are already in [salesforce.md](salesforce.md): Named Credential, External Credential, the permission set that grants the **principal** (without it Apex 401s while curl works), `req.setTimeout(120000)`, `"stream": false`, and poll patterns A/B/C (one poll per transaction). Do not rewrite that page from scratch.

The worker does **not** meet the Phase F code bar yet:

- `apps/worker/app/translation.py` **rejects** `stream: true`. Salesforce keys must accept it, force a JSON body, and set `x-cloudiator-stream-downgraded: true`.
- `max_response_bytes` is stored on the key (default 1 MB) and is not enforced on the response. An oversized body must become an artifact id plus a truncated preview.
- Missing tests: `apps/worker/tests/test_sf_stream_downgrade.py`, `apps/worker/tests/test_response_size_cap.py`.

New Agent chat on the Mini. Model **Claude Sonnet 5**. Auto off. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/salesforce.md`. Paste:

```
Phase F only. Repo is /Users/ashrafrezk/cldM4. Docs in docs/salesforce.md already cover Named Credential, the External Credential principal permission set, setTimeout(120000), stream false, and the three poll patterns. Do not duplicate that prose.

1. Salesforce keys (force_no_stream): if the body has stream true, serve non-streaming JSON and set x-cloudiator-stream-downgraded: true. Do not 400.
2. Enforce max_response_bytes (1 MB) for those keys. Oversized JSON returns an artifact id plus a truncated preview, not a multi-megabyte body.
3. Tests: apps/worker/tests/test_sf_stream_downgrade.py and apps/worker/tests/test_response_size_cap.py.
4. Leave mlx-whisper and /v1/audio/transcriptions out unless I ask. Do not pull gpt-oss:20b. Do not run FLUX 8-bit.

Prove: cd /Users/ashrafrezk/cldM4/apps/worker && .venv/bin/pytest tests/test_sf_stream_downgrade.py tests/test_response_size_cap.py -q
```

After that commit is on `main`:

```bash
cd /Users/ashrafrezk/cldM4
git checkout main
git pull origin main
launchctl kickstart -k gui/$UID/ai.cloudiator.worker
```

Then in a Developer Edition or sandbox (operator-checklist §10 — all of it is still blank):

1. Mint a **Salesforce engineer** key in `/console`. Record only the `public_id` in the checklist.
2. Named Credential `Cloudiator` → `https://api.cloudiator.org`, External Credential principal, permission set assigned to the running user. Steps in [salesforce.md](salesforce.md).
3. Download `GET /v1/openapi.json?target=salesforce` with that key and import it into External Services. `openapi` must be `3.0.3`. The importer must succeed.
4. Run the dashboard Apex snippet. Chat JSON comes back in under 120 seconds.
5. One poll pattern (A, B, or C in [salesforce.md](salesforce.md)) reads a finished image job. Each poll is its own transaction.
6. Cloudflare, before the first callout: Security Level **Essentially Off** and Browser Integrity Check **OFF** for `api.cloudiator.org` (operator-checklist §2a). Bot Fight Mode is already off. The WAF skip rule `skip-sk-cld-salesforce` is already on.

```bash
/usr/bin/curl -s -A 'Salesforce/1.0' -o /tmp/r.txt -w '%{http_code}\n' https://api.cloudiator.org/v1/health
/usr/bin/head -c 200 /tmp/r.txt
```

The body must be JSON. HTML means Apex will fail.

mlx-whisper stays optional and uses the same exclusive slot as FLUX. Skip it for v1.

## 6. Unattended boot and alerting

These are still blank in [operator-checklist.md](operator-checklist.md). A power cut with FileVault on stops at the unlock screen: no LaunchAgent, no Ollama, Salesforce sees 503, and nobody is paged.

- Tick exactly one of §6 A / B / C. Recommended: FileVault on, a UPS, manual unlock.
- Automatic login for `ashrafrezk`. Energy: computer does not sleep; wake for network; start up after a power failure.
- `SLACK_WEBHOOK_URL` in `/Users/ashrafrezk/Cloudiator/.env`. Install the 2-minute health ping from [host-setup.md](host-setup.md) §10. Stop the worker once and confirm the alert fires, then start it again.

Also still open, and worth doing in the same sitting:

- Read the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/). Show “© OpenStreetMap contributors” wherever geocode results are shown to a person.
- Write the measured disk number into checklist §0: **375.3 GB free** on 2026-09-27 (`/v1/health` `free_disk_gb`). Fill §8 with `gemma4:e4b-it-qat` and `nomic-embed-text` actually installed. §9 FLUX rows are already filled.

## Stay off

- `ollama pull gpt-oss:20b`, `gemma4:26b`, `gemma4:31b`, Q8, bf16, or `*:mlx`
- FLUX 8-bit, and any FLUX run without `--low-ram`
- `OLLAMA_MAX_LOADED_MODELS` other than 2, `OLLAMA_NUM_PARALLEL` other than 1, `uvicorn` workers other than 1
- Docker for inference, Netlify inference, `apps/gateway/`, a shared dashboard password
