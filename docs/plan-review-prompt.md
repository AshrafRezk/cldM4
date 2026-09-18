# Plan review prompt (A+ pass)

Use this **before Phase A**, and again if the plan changes.

> **Status: the first pass has been run.** Results are in [plan-review-findings.md](plan-review-findings.md), the fixes are patched into `PLAN.md` and `docs/`, and the operator inputs it asked for are now [operator-checklist.md](operator-checklist.md). Re-run this prompt after any significant plan change, not before Phase A.

## Cursor UI (do not skip)

| Setting | Value |
| --- | --- |
| Plan | Cursor Pro Plus |
| Mode | **Agent** or **Plan** (not Ask) |
| Model | **Claude Opus 5** — newest Opus in the picker. Fast variant optional. **Not** Auto, **not** Sonnet, **not** Grok, **not** Composer |
| Context | Max Mode / 1M **on** |
| Auto-run | Off |
| Privacy Mode | On |
| Attach | `@PLAN.md` `@README.md` `@AGENTS.md` `@docs/` `@.cursor/rules/cloudiator.mdc` `@.env.example` |

Opus 5 is the plan auditor. Grok/Sonnet will miss the traps that break a Mini follow-through.

---

## Paste this as the first (and only) user message

```
You are a principal engineer reviewing Cloudiator (repo cldM4) the week before a Mac Mini M4 24GB implements it in Cursor, one phase at a time.

GOAL
Make PLAN.md + docs/ A+ followable: a later Opus Agent must be able to execute docs/cursor-phases.md without improvising architecture, hitting silent RAM death, Salesforce 10s timeouts, Cloudflare bot challenges, or license/ToS bans.

CONSTRAINTS
- Edit markdown (and .env.example / .cursor/rules) ONLY. No apps/, no ollama pull, no git push unless I ask.
- PLAN.md remains source of truth. Fix contradictions in place; do not write a second competing bible.
- Do not add video generation, Docker inference, Netlify inference, 70B/120B, unrestricted eval, or face recognition.
- Keep v1 scope. Prefer adding a "Failure if skipped" note over new features.
- Token budget: unlimited. Be thorough. Do not summarize away details an implementer needs.

METHOD
1. Read every file in the repo (PLAN.md, README.md, AGENTS.md, docs/*, .cursor/rules/*, .env.example).
2. Produce a short Findings list (P0/P1) in docs/plan-review-findings.md.
3. Patch the docs so P0/P1 are fixed in the actual instructions, not only in the findings file.
4. Stop. Do not start Phase A code.

AUDIT CHECKLIST (every item: pass, or patch the plan)

A. Contradictions
- keep_alive=-1 vs OLLAMA_KEEP_ALIVE=30m
- When gpt-oss:20b is pulled (catalog vs Phase A)
- FastAPI metal_lock vs uvicorn workers>1 (must be workers=1 / single process)
- Auth: worker validates vs optional Cloudflare Worker
- mermaid-cli / kaleido Chromium RAM vs "tools skip GPU lock"
- Dashboard "shared admin password" vs Cloudflare Access

B. Mini / Metal / RAM
- arm64-only Python 3.11 (reject Rosetta)
- FileVault on; Time Machine and Spotlight exclude ~/.ollama and HuggingFace cache
- macOS Sequoia Local Network permission for cloudflared
- Ollama .app vs brew ollama conflict
- Exclusive slot teardown if mflux crashes mid-job (always reload 9B in finally)
- Disk-full and artifact TTL
- memory_pressure polling implementation note
- First-run mflux weight download size vs 25s HTTP

C. Network / Cloudflare / Neon
- Bot Fight Mode / "I'm Under Attack" WILL block Salesforce Apex. WAF skip rule when Authorization starts with Bearer sk-cld-
- Named tunnel only; no quick tunnels
- Never ingress :11434
- Neon: Mini is long-lived → small Postgres pool (size 2). Netlify functions use Neon serverless HTTP or pooled, 10s is OK for INSERT
- Key revoke cache TTL 60s documented
- Usage write retry queue if Neon down (chat must still return)

D. Salesforce
- Default callout 10s; snippet MUST setTimeout(120000)
- Apex heap ~6MB: never return PNG/PDF base64; signed URLs only
- Named Credential + External Credential custom header
- Salesforce keys force stream=false
- Jobs + Flow poll; cumulative 120s callout budget
- External Services OAS: generate 3.0/3.1 that Salesforce can import; no unsupported keywords
- CORS irrelevant for Apex; still required for browser apps
- File upload from Apex is painful: document JSON rows vs multipart vs Files content

E. API contract completeness (so OpenAI SDKs don't explode)
- Unsupported: n>1, logprobs, image variation, assistants
- model alias map (gpt-4o → qwen3.5:9b) optional and scoped
- tools vs Ollama native tools: FastAPI owns tool loop; cap iterations (e.g. 8)
- Vision: downscale images before Ollama; max dimension
- Idempotency-Key for jobs
- X-Request-Id in every response
- /v1/health: unauthenticated, no secrets, do not leak key hashes; queue_depth OK

F. Security
- argon2id params
- signed artifact HMAC + 15min expiry + no listing
- DuckDB SQL allowlist (already stated — add injection examples)
- SSRF denylist
- Strip EXIF default
- No prompt logs for Salesforce preset
- Admin routes behind Cloudflare Access, not a query-string token

G. Install reproducibility
- Pin uv python == 3.11.x
- Commit uv.lock / package-lock in later phases
- brew formulae listed
- mermaid-cli Chromium warning: skip or isolate; Graphviz is the safe default if Chrome RAM spikes
- Nominatim User-Agent + 1 rps or they get banned
- LaunchAgent: replace REPLACE user paths; load via gui domain `launchctl bootstrap gui/$UID`

H. Phase DoD
- Each phase in docs/cursor-phases.md has: model, files that must exist after, curl/commands to prove DoD, rollback
- Phase A: uvicorn workers=1, bind 127.0.0.1, ollama ps count <= 1
- Phase B: phone HTTPS test + 401 + WAF skip note
- Missing automated tests listed as files to create, not "test later"

I. Operator inputs that are still placeholders
- Domain, Neon, Cloudflare account, Slack webhook, contact email for Nominatim
- Add docs/operator-checklist.md: fill these BEFORE Phase B

OUTPUT
- docs/plan-review-findings.md (P0/P1/P2)
- Patched PLAN.md and docs so a Mini agent cannot miss P0s
- Update docs/cursor-phases.md DoD commands
- Keep the voice operational, not marketing
```

---

After the review lands, `git pull` on the Mini, then start **Phase A** with Opus 5 as in `docs/cursor-settings.md`.
