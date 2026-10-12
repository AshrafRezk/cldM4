# Next steps — finish v1 (2026-09-27)

**Phases A–E are proven on the Mini at `cde136e`.** Live check the same day: `HEAD` `cde136e`, state `idle_hot_9b`, loaded `gemma4:e4b-it-qat` + `nomic-embed-text`, and `POST` to `/v1/tools/ocr`, `/v1/tools/geocode`, `/v1/jobs`, and `/v1/chat/completions` all returned **401**. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not pull `gpt-oss:20b`. Do not run FLUX 8-bit.

Repo on the Mini: `/Users/ashrafrezk/cldM4`  
Env (outside git, `chmod 600`): `/Users/ashrafrezk/Cloudiator/.env`  
Secrets stay in the password manager, not this file. Blanks: [operator-checklist.md](operator-checklist.md).

v1 is finished when every box in [Finish line](#finish-line) is checked. Work top to bottom. Steps 1–4 are operator actions on the Mini, Neon, Netlify, and Cloudflare. Step 5 is the only remaining code phase.

**To use what is already live** — mint a key, send a playground chat, and call every tool Phases A–E shipped — follow [using-console.md](using-console.md).

## Proven — do not redo

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords. Playground CORS allows `https://app.cloudiator.org`.

**Dashboard:** `https://app.cloudiator.org` on Netlify, Cloudflare Access only. Landing at `/`. Operator console at `/console`. `DATABASE_URL` is server-side only.

**Phase D (Mini):** OCR on a large-font PNG returned `INVOICE 42` with no extra model. Geocode `Cairo, Egypt` was `30.0443879, 31.2357257`; the repeat was `0.005s` from the SQLite cache. A chat-only key got 403 on OCR. Signed / tampered / traversal artifact URLs were 200 / 404 / 404.

**Phase D2 (Mini):** Fruit CSV query grouped to apples 5 and pears 4. Chart returned a matplotlib PNG. Hot model stayed loaded.

**Phase D3 (Mini):** `sf_id` `001D000000IRt53` became `001D000000IRt53IAD`. A mermaid request rendered with Graphviz (`/opt/homebrew/bin/dot`). Hot model stayed loaded.

**Phase E (Mini):** Job `dcbfbc7dc5af4e7e91967a7e5c057496` succeeded with artifact `8034c949723d4c1caca9c7838abfbb06` on 4-bit schnell `--low-ram` (peak 8.43 GB MLX, wall clock 1:56). Killing `mflux-generate` mid-job (`1bf553e4641a47f29159da6f307e2317`) left chat working (`Hi.`), Gemma reloaded, and the failed job still present after `kickstart`. Weights: `/Users/ashrafrezk/Cloudiator/models/flux-schnell-4bit`.

`/v1/health` reporting `db: "unknown"` is expected. That route does not call Neon.

## Finish line

- [ ] **1. Reboot clears leftover swap** so `/v1/health` returns `"ok": true` and `swap_used_mb` is 0. *(Mini operator — cannot do from Cloud Agent.)*
- [ ] **2. Playground chat** from `https://app.cloudiator.org/console` returns JSON and a `usage_daily` row appears. *(Mini / browser with Access.)*
- [ ] **3. Neon retention nightly on the Mini.** Repo now has `scripts/run-neon-retention.sh` + `scripts/install-retention-launchagent.sh`. On the Mini: run the installer, then one manual `run-neon-retention.sh`. Do not use `pg_cron`.
- [ ] **4. `cloudiator.netlify.app` → `https://app.cloudiator.org`.** Redirect is already in `apps/dashboard/netlify.toml`. Prove after production deploy: `curl -sI https://cloudiator.netlify.app/ | grep -i location`.
- [x] **5. Phase F worker code** — `force_no_stream` accepts `stream: true` with `x-cloudiator-stream-downgraded: true`; `max_response_bytes` returns artifact + truncated preview. Tests: `test_sf_stream_downgrade.py`, `test_response_size_cap.py`. **Still open on a Salesforce org:** External Services import + real Apex callout ([salesforce.md](salesforce.md)).
- [ ] **6. Unattended boot** — one FileVault policy in operator-checklist §6, auto-login, no computer sleep, and a tested health alert. *(Mini operator.)*

After v1 is green, next bets (voice console, CRM write-back, WhatsApp, RAG, rembg, …) live in **[future-phases.md](future-phases.md)**.

Explicitly **not** required to finish v1: `gpt-oss:20b`, FLUX 8-bit, vLLM-metal, a Cloudflare Worker, `apps/gateway/`. Phase G (SIM phone) is a separate product phase, not a v1 finish-line checkbox.

---

## 1. Clear leftover swap (Mini)

**Yes — reboot the Mini first** if `/v1/health` shows `"ok": false` and `swap_in_use` (even a few dozen MB counts). After unlock + login, run the one-shot helper (or the steps below):

```bash
cd /Users/ashrafrezk/cldM4
git pull origin main
scripts/post-reboot-finish-line.sh
```

That pulls Phase F, kickstarts the worker, installs Neon retention, and prints health. The 19.08 GB FLUX run (no `--low-ram`) left swap in use historically. At 17:42 UTC on 2026-09-27 health was:

```json
{"ok": false, "state": "idle_hot_9b", "swap_used_mb": 1611.88, "degraded": ["swap_in_use"], "free_disk_gb": 375.3, "pressure": "normal"}
```

FileVault policy is still unticked (§6). A reboot stops at the unlock screen until someone types the password. After login, LaunchAgents must be running again.

```bash
cd /Users/ashrafrezk/cldM4
git pull origin main
# reboot from the Apple menu, unlock, log in as ashrafrezk, then:
launchctl print gui/$UID/ai.cloudiator.worker | head -5
/usr/bin/curl -s http://127.0.0.1:8080/v1/health | /usr/bin/python3 -m json.tool
```

Expect `"ok": true`, `"degraded": []`, `swap_used_mb` 0, `state` `idle_hot_9b`, and both models loaded. If `ok` is still false, read `degraded` before changing models.

## 2. Playground usage row

Open `https://app.cloudiator.org/console` (Cloudflare Access, no password form). Mint a key and send one playground chat, as in [using-console.md](using-console.md). The response is the model's text. On the Usage tab, a row for today exists in `usage_daily` for that key. The chart reads the rollup, not raw `usage_events`. A row can take about 15 seconds to appear.

## 3. Schedule Neon retention

Free-tier storage fills if raw `usage_events` are kept forever, and then **key minting fails**. The statement is `infra/neon-retention.sql` (same SQL as [schema.md](schema.md)).

Run it from the Mini, not from `pg_cron`. The Neon compute scales to zero, and `pg_cron` only fires while that compute is awake — a missed night is dropped, not retried. The Mini is already on. A LaunchAgent at 03:15 local runs the SQL through the worker's Neon client, which wakes the compute, then lets it suspend again.

```bash
cd /Users/ashrafrezk/cldM4
git pull origin main
mkdir -p /Users/ashrafrezk/Cloudiator/logs
scripts/install-retention-launchagent.sh
scripts/run-neon-retention.sh
launchctl print gui/$UID/ai.cloudiator.retention | head -12
```

The first command runs the SQL immediately. Expect a line like `retention ok: usage_events=… older_than_30d=0 usage_daily_rows=…`. `older_than_30d=0` means the delete worked. Today's playground rows stay; only events older than 30 days are removed, and the rollup covers completed days.

`launchctl print` should show `state = not running` and the program path above. That is a calendar job, not a always-on process. It runs at 03:15 while you are logged in. Do not `source` `/Users/ashrafrezk/Cloudiator/.env`. Tick operator-checklist §3 when that print succeeds.

Do not point the worker request path at this query. `/v1/health` must stay off Neon.

## 4. Send the Netlify hostname to Access

Domain management cannot remove `cloudiator.netlify.app`. That page says the project is always reachable there, and Netlify uses the name for deploys. `app.cloudiator.org` is already the primary domain.

The yellow **Pending DNS verification** badge is Cloudflare sitting in front of Netlify. Click it and confirm the record it wants. In the Cloudflare DNS table for `cloudiator.org`, `app` must be a CNAME to `cloudiator.netlify.app` and stay **proxied** (orange cloud). Access only runs on a proxied hostname. Leave the proxy on. If the playground already loads, the badge can stay yellow: Netlify's checker cannot see through Cloudflare, and turning the cloud grey removes Access.

The **repo-root** `netlify.toml` (used when `base = apps/dashboard`) forces `cloudiator.netlify.app` → `https://app.cloudiator.org/:splat` with a host-conditioned 301. `apps/dashboard/public/_redirects` mirrors it into `dist/`. After that is on `main` and Netlify finishes a **production** deploy:

```bash
/usr/bin/curl -sI https://cloudiator.netlify.app/ | /usr/bin/grep -i -E 'HTTP/|location:'
```

Expect `301` and `location: https://app.cloudiator.org/`. An incognito window on `https://app.cloudiator.org` is still a Cloudflare Access challenge.

## 5. Phase F — Salesforce pack

Docs for the org are already in [salesforce.md](salesforce.md): Named Credential, External Credential, the permission set that grants the **principal** (without it Apex 401s while curl works), `req.setTimeout(120000)`, `"stream": false`, and poll patterns A/B/C (one poll per transaction). Do not rewrite that page from scratch.

**Phase F worker code is in the repo** (`resolve_stream_downgrade`, `enforce_max_response_bytes`, `tests/test_sf_stream_downgrade.py`, `tests/test_response_size_cap.py`). After that commit is on `main` and pulled on the Mini:

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
