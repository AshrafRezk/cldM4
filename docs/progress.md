# Execution checklist

This is the living status board. Operator blanks still live in [operator-checklist.md](operator-checklist.md). Phase commands live in [cursor-phases.md](cursor-phases.md).

**Last updated:** 2026-09-19  
**Current phase:** A (code in git; Mini proofs not yet run)  
**This Mini (from operator screenshots):** 2024 Mac mini, **Apple M4, 24 GB**, serial `F47YLJF2M`, **443 GB free**, hostname `cloudiator.local`, Wi-Fi **Ash & Mimi** `192.168.100.51` (MAC `d0:11:e5:94:6b:23`), `uname -m` = **arm64**, auto-login **Cloudiator**, FileVault **Off (policy C)**, network time on, **no UPS**. Keyboard in the room.

**Account note:** The appliance login **Cloudiator** is the original user renamed in Users & Groups. Unix short name / `$HOME` is still **`ashrafrezk`** (`ashrafrezk@cloudiator` in Terminal). A second Admin named **Ashraf** exists for updates. Install Ollama, `~/Cloudiator/.env`, and LaunchAgents on **this** session — do not switch users.

Legend: **done** · **not done** · **you (manual on the Mini / in vendor dashboards)**

---

## You must do (nothing in git can finish these)

These are blocked on your Mac Mini, accounts, or Cloudflare/Neon/Netlify clicks. The agent cannot complete them from this cloud VM.

### Day 0 — hardware and Mac Mini

#### Proven from screenshots (2026-09-19)

- [x] Right machine: **Mac mini 2024, Apple M4, 24 GB**
- [x] Disk: **443 GB free** of 494 GB (need ≥ 120 GB)
- [x] Display connected (screen-only desk is OK)
- [x] Energy: prevent sleep when display off, wake for network, start up after power failure
- [x] Local hostname `cloudiator.local`
- [x] Appliance user **Cloudiator** is the renamed original account (Unix name **`ashrafrezk`**, home `/Users/ashrafrezk`). Second Admin: **Ashraf**. Auto-login is this same account, so LaunchAgents in `gui/$UID` match.
- [x] Screen Sharing **LAN only** at `192.168.100.51`, Administrators only
- [x] **Ethernet skipped on purpose.** Wi-Fi-only accepted — [hardware-and-network.md](hardware-and-network.md) §3a. Do not turn Wi-Fi off.
- [x] **Automatically log in as `Cloudiator`**
- [x] Date & Time → **Set time and date automatically** (Apple `time.apple.com`, Pacific)
- [x] `uname -m` → **arm64** (Terminal as `ashrafrezk@cloudiator`)
- [x] Keyboard in the room
- [x] **No UPS** — operator will not buy one. Power cuts mean downtime until a human is at the Mini.
- [x] **FileVault Off (policy C).** macOS: “FileVault can’t be turned on because automatic login is enabled.” Compensating control: home desk, keyboard, Screen Sharing LAN-only, no UPS.
- [x] Wi-Fi **Ash & Mimi**, DHCP `192.168.100.51`, router `192.168.100.1`, MAC `d0:11:e5:94:6b:23`, proxies off.

#### Router (done)

- [x] Router `192.168.100.1` (WE / Huawei **HG8145V5**): **DHCP Static IP** binds MAC `d0:11:e5:94:6b:23` → `192.168.100.51` (saved row, 2026-09-19).
- [x] **Forward Rules empty:** IPv4 Port Mapping, Port Trigger, IP Mapping, and DMZ all have no rows. WAN 22 / 5900 / 8080 / 11434 are not forwarded. Do not add any.

Hardware Day 0 is done. Logout of the router. Next is software on the Mini.

#### Then software on the Mini (this is the remaining manual work)

- [x] **Cursor** is in `/Applications` (screenshot 2026-09-19). Still set Privacy Mode on and Auto off per [cursor-settings.md](cursor-settings.md) when you use it on this Mini.
- [x] **Ollama.app** is in `/Applications`; CLI `/usr/local/bin/ollama` **0.34.2**; no Homebrew ollama. Open it so the menu-bar app is running.
- [ ] **Xcode Command Line Tools** — Mini Terminal: `xcode-select: No developer tools were found`. `git clone` never created `~/cldM4`, so `.env` and `mac-setup.sh` did not run.

#### Then software on the Mini (remaining)

- [ ] Install Xcode CLT (GUI prompt or `xcode-select --install`), wait until `git --version` prints a version
- [x] Repo cloned at `~/cldM4` on branch `cursor/phase-a-openai-shim-ee9d`; `~/Cloudiator/.env` copied (`chmod 600`).
- [ ] **Homebrew** — `mac-setup.sh` aborted: `Homebrew missing`. Install from https://brew.sh then re-run the script.

#### Then software on the Mini (remaining)

- [ ] Copy repo `.env.example` → `~/Cloudiator/.env`, `chmod 600`, **outside git**
- [ ] Run `scripts/mac-setup.sh` **on the Mini** (arm64 gate, brew deps, exclusions, newsyslog, `qwen3.5:9b` + `nomic-embed-text` pulls only). Overnight is fine on Wi-Fi (~7 GB).
- [ ] Run each binary once in Terminal so Sequoia **Local Network** permission is granted, then `scripts/install-launchagents.sh`
- [ ] Set the Ollama.app env from `infra/launchagents/ollama.env` (`OLLAMA_MAX_LOADED_MODELS=2`)
- [ ] Run the Phase A **Prove it** commands in [cursor-phases.md](cursor-phases.md) and paste results into operator-checklist **§8–9**
- [ ] `ollama show qwen3.5:9b` — confirm **tools**; note **vision**. Tag was verified on ollama.com (6.6 GB, text+image, tools) but **your Mini must still pull and show it**

### Before Phase B (operator-checklist §§1–5 must have no blanks)

- [ ] Domain whose nameservers are Cloudflare; zone **Active**
- [ ] Cloudflare: named tunnel `cloudiator-mini`, DNS `api.<domain>` proxied
- [ ] Bot Fight Mode **OFF**, Browser Integrity Check off, no Turnstile, no “I’m Under Attack” on `api.`
- [ ] WAF Skip rule on `Bearer sk-cld-`; rate limit keyed on **Authorization**, not IP
- [ ] Cloudflare Access on `app.<domain>` and `api.<domain>/v1/admin*` — record team domain + **AUD**
- [ ] Neon project, **pooled** `DATABASE_URL`, schema from `docs/schema.md`
- [ ] Nominatim contact email (real mailbox) for `NOMINATIM_USER_AGENT`
- [ ] Phone-on-cellular test of `https://api.<domain>/v1/health` after the tunnel is up

### Later (not this PR)

- [ ] Netlify site for the dashboard (Phase C)
- [ ] Salesforce Named Credential + permission set on the External Credential **principal** (Phase F)
- [ ] Phase E FLUX warmup **in Terminal**, never from the worker (`mflux` + local 4-bit weights)
- [ ] Slack (or similar) health webhook before calling it production

---

## Phase status

| Phase | What | Status |
| --- | --- | --- |
| 0 | Operator inputs (domain, Cloudflare, Neon, boot policy) | Hardware Day 0 **done**. Cloud accounts §§1–5 still needed **before Phase B** |
| **A** | FastAPI OpenAI shim, health, metal lock, SSRF, context guard, LaunchAgent templates, tests | **Code done in git.** Mini live proofs **you** |
| B | Neon keys, argon2id, tunnel, public HTTPS, Salesforce OpenAPI 3.0.3 | **Not started** (blocked on Phase 0 + A Mini proofs) |
| C | Netlify dashboard, mint keys, usage, OpenAPI download | **Not started** |
| D | Tool registry, OCR, maps, artifact signing, tool loop | **Not started** |
| D2 | Charts, stats, DuckDB sandbox | **Not started** |
| D3 | Image ops, docs, Graphviz, SF IDs | **Not started** |
| E | FLUX exclusive slot, jobs queue, optional `gpt-oss:20b` | **Not started** |
| F | Salesforce pack, optional Whisper | **Not started** |

---

## Phase A — done in this repository

- [x] `apps/worker` FastAPI + uv + Python **3.11** pin (`.python-version`)
- [x] `GET /v1/health` — unauthenticated, no Neon, no secrets; `db` is `"skipped"` until Phase B
- [x] `POST /v1/chat/completions` OpenAI JSON ↔ Ollama `/api/chat`
- [x] `POST /v1/embeddings` + `nomic-embed-text` `search_query:` prefix
- [x] `GET /v1/models` from live `ollama tags` only (never from `HEAVY_MODEL` env)
- [x] `metal_lock` + state machine; lock released if the body raises
- [x] `cpu_heavy_lock` semaphore capacity 1
- [x] Memory poller every 5s via `asyncio.create_subprocess_exec` (`sysctl` on Darwin)
- [x] `X-Request-Id` on success and error responses
- [x] `num_ctx` 4096, `max_tokens` 512, pre-flight `400 context_length_exceeded`
- [x] Explicit `keep_alive`: `-1` hot model + embedder, `0` anything else
- [x] Qwen3.5 `think: false` by default (avoids burning `max_tokens` inside `<think>`)
- [x] Reject `n>1`, `logprobs`, `top_logprobs`, `best_of`, `logit_bias`
- [x] SSRF guard: `https`/`data:` only; DNS-resolve; block loopback, RFC1918, link-local, CGNAT; downscale to 1024px; max 4 images
- [x] Bind documented as `127.0.0.1:8080`, `uvicorn --workers 1`; refuse `WEB_CONCURRENCY≠1`
- [x] Refuse to boot unless `OLLAMA_MAX_LOADED_MODELS=2` (production)
- [x] LaunchAgent template + path substitution (`scripts/install-launchagents.sh`)
- [x] `scripts/mac-setup.sh`, `scripts/smoke-phase-a.sh`
- [x] Tests: `test_openai_translation.py`, `test_metal_lock.py`, `test_ssrf_guard.py`, `test_context_guard.py` (+ HTTP smoke)
- [x] Off-Mini unit tests: **53 passed** (2026-09-19, Linux x86_64, `CLOUDIATOR_ENV=test`)

Production boot still **aborts on Linux / x86_64**. Unit tests set `CLOUDIATOR_ENV=test` so they can run off-Mini.

## Phase A — not done until you run it on the Mini

- [ ] `uname -m` and venv Python both **arm64**
- [ ] `ollama pull qwen3.5:9b && ollama show qwen3.5:9b` (tools + vision recorded in §8)
- [ ] `ollama pull nomic-embed-text` only — **do not** pull `gpt-oss:20b` / 27B / 70B / 120B
- [ ] `pgrep -fc "uvicorn app.main:app"` → **1**
- [ ] `lsof` shows **127.0.0.1:8080**, not `*:8080`
- [ ] Live `curl` chat + embeddings against loopback
- [ ] `ollama ps` → at most **one** generative model (+ `nomic-embed-text`)
- [ ] `sysctl vm.swapusage` → used **0.00M**
- [ ] `~/Library/LaunchAgents/ai.cloudiator.worker.plist` loaded via `launchctl bootstrap` (not `load`)
- [ ] `python -c "import Vision"` in the venv

Rollback (Mini): `launchctl bootout gui/$UID/ai.cloudiator.worker`, `git checkout -- apps/worker scripts`, `rm -rf apps/worker/.venv`. Models stay on disk.

---

## What this agent will not do in later chats unless you ask

- Phase B+ while operator-checklist §§1–5 are blank
- `ollama pull` of 20B/27B/70B/120B
- Docker for inference, Netlify inference, `apps/gateway/`
- Filling real domain / Neon / Cloudflare secrets into git
