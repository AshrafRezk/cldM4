# Where we are — 2026-09-27

**The API is up. The product is not ready for a client who will depend on it.**

Public chat: `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`.

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md). Architecture: [PLAN.md](../PLAN.md). Phase prompts: [cursor-phases.md](cursor-phases.md).

This cloud checkout is not the Mini. Do not run `ollama pull`, LaunchAgents, or `scripts/mac-setup.sh` here. Worker, models, and smokes are proven only on the Mini.

---

## Proven (Phases A and B, Mini, 2026-09-20)

| Surface | State |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI JSON in and out. Gemma 4 E4B QAT (`gemma4:e4b-it-qat`). Non-streaming only. |
| `POST /v1/embeddings` | `nomic-embed-text`, slot 2, `keep_alive: -1`. |
| `GET /v1/models` | Live `ollama tags` intersected with the key. |
| `GET /v1/health` | Local, no Neon round trip. |
| Keys | `sk-cld-` in Neon, argon2id, 60s cache, per-key rpm. Mint and revoke via `python -m app.dbtool` on the Mini. |
| Usage | SQLite outbox, flushed to Neon. `GET /v1/usage` exists. |
| OpenAPI | `GET /v1/openapi.json`, and `?target=salesforce` emits 3.0.3 with no `oneOf`/`anyOf`/`allOf`. |
| Admin | `Cf-Access-Jwt-Assertion` on `/v1/admin*`. Loopback `ADMIN_TOKEN` only. |
| Tunnel | Chat 200 with a real key from the Air. Garbage key is FastAPI JSON 401, not Cloudflare HTML. `:11434` is not in the ingress. |
| Tests in repo | Auth, key cache, outbox, OpenAPI filter, metal lock, SSRF, context guard, routes. Hermetic: no Ollama, no Neon. |

`DEFAULT_MODEL=gemma4:e4b-it-qat`. `NOMINATIM_USER_AGENT` is quoted in the Mini `.env`.

---

## Not proven, and still required before v1

These were explicitly postponed on 2026-09-20. They are still open.

- External Services import of the Salesforce OpenAPI into a dev org (Phase F).
- Neon-down drill: chat still succeeds on a cached key, outbox depth climbs, then drains.
- Operator checklist §8 and §9: the model row and the tok/s, RAM, and swap measurements are blank. The plan's RAM table is still an estimate.
- Checklist §2a: Security Level and Browser Integrity Check for `api.cloudiator.org` are unchecked. The WAF skip rule covers `Bearer sk-cld-`. Finish the hostname settings anyway.
- Checklist §6: no boot policy. With FileVault on, a power cut stops at the unlock screen and the API stays down until a human types the password.
- Checklist §7: no Slack (or other) health ping. An outage is invisible.
- `infra/neon-retention.sql` is not scheduled. Raw `usage_events` will fill the free tier and key minting will start failing.

---

## What a client can do today

One thing: send a non-streaming chat or embeddings call with a key that an operator minted over SSH.

They cannot:

- Sign in anywhere and mint their own key. `app.cloudiator.org` has Cloudflare Access and no site behind it. Netlify is blank (checklist §4).
- See usage without querying Neon.
- Call a tool. There is no `apps/worker/tools/`, no OCR, no geocode, no chart, no DuckDB.
- Generate an image, submit a job, or poll one. `POST /v1/jobs` is named in error bodies and in the OpenAPI fragments. The route is not registered.
- Stream. `stream: true` is `400 not_supported` for every key. The Salesforce downgrade header is not implemented.
- Upload audio or receive audio. See below.

Concurrency is one Metal generation. A second chat waits up to 2 seconds, then `429 metal_busy`, and the error tells them to use a jobs API that does not exist yet.

---

## Speech

| Question | Answer |
| --- | --- |
| Do we have a model that **speaks** well? | **No.** Gemma 4 writes text. Nothing on the box synthesises speech. `/v1/audio/speech` does not exist. |
| Do we have a model that **listens** well? | **Not in the product.** Whisper large-v3-turbo is the planned listener (Arabic and English, ~1.6 GB, exclusive slot). It is not pulled and not wired. Gemma 4 can accept audio in the lab; the worker does not expose that, and the E4B audio path in Ollama has been unstable. Do not sell it. |

When speech is built, it is two different models, both exclusive (they unload Gemma for the call):

- **Listen:** `mlx-community/whisper-large-v3-turbo` via `mlx-whisper`. Phase F. `POST /v1/audio/transcriptions`. This is the one that listens, including Arabic.
- **Speak, not Arabic:** Kokoro-82M, Apache 2.0, through `mlx-audio`, a few hundred MB. Languages: English, Japanese, Mandarin, French, Spanish, Italian, Portuguese, Hindi. Not in v1 until a phase says so. Official Qwen3-TTS is higher quality on its ten languages and also has no Arabic. There is no small model on this plan that speaks Arabic well. Do not add a 1.7B+ TTS beside Gemma.

The `speech` preset in `packages/schema/scopes.json` (`transcriptions`, `tools.audio_ops`) must not be minted until those routes exist. `tools.audio_ops` is ffmpeg, not a model, and it is also unbuilt.

---

## Path to a first real client

Do these in order. Do not start D, E, or F while the rows above them are open: a client with tools and no alerting still pages you by failing.

### 1. Operator, on the Mini and in Cloudflare (no new product code)

1. Tick exactly one boot policy in checklist §6. Enable automatic login for the appliance user. Energy: the computer must not sleep.
2. Put a health ping on `/v1/health` every 2 minutes and a Slack (or equivalent) webhook. Stop the worker once and confirm the alert.
3. Schedule `infra/neon-retention.sql`.
4. Finish checklist §2a (Security Level, Browser Integrity Check) and read the Nominatim policy (§5).
5. Fill §8 from `ollama show` / `ollama ps`, and §9 from a timed chat. If `sysctl vm.swapusage` is not zero, stop and shrink the config before any client.

### 2. Phase C — dashboard (next code, Mac or anywhere, not the Mini's Metal)

Netlify site, `app.cloudiator.org`, Cloudflare Access already in front. No login form. Server functions only for Neon.

Mint a key, show it once, revoke it (say the 60s cache out loud), usage from `usage_daily`, both OpenAPI downloads, the Apex snippet with `req.setTimeout(120000)` and `"stream": false`. `npm run build` then `grep -r neon.tech dist/` finds nothing.

Until this exists, every client key is an SSH session. That is acceptable for a one-org dogfood week and unacceptable as the steady state.

Copy-paste for that chat is the Phase C block in [cursor-phases.md](cursor-phases.md), with the hostnames already filled in the 2026-09-20 block at the bottom of this file.

### 3. Dogfood one chat key

One Salesforce org or one website, chat and embeddings only, operator on call, written limits: no stream, no tools, no images, no speech, one request at a time. Run the Neon-down drill during that week.

### 4. Then the product they were sold

| Phase | Unlocks | Where |
| --- | --- | --- |
| D | OCR, geocode, tool loop (8 iterations, 75s) | Mini |
| D2 | Charts, stats, locked-down DuckDB | Mini |
| D3 | Image ops, docs, diagrams, Salesforce ids | Mini |
| E | FLUX jobs, idempotency, crash recovery. Only then is `POST /v1/jobs` real. Optional `gpt-oss:20b`. | Mini |
| F | Named Credential, External Services import, stream downgrade, optional Whisper | Mini + a dev org |

v1 done is still [PLAN.md](../PLAN.md) §22. Speech-to-text is the optional tail of Phase F. Speech synthesis is not in v1.

---

## Phase C copy-paste (unchanged intent)

Cursor **Pro Plus**. Agent mode. **Auto off.** Privacy Mode on. Model: **Claude Sonnet 5**. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md` `@docs/env.md`.

Netlify site env (server functions only, never the browser bundle):

- pooled `DATABASE_URL` (`-pooler` in the host)
- `PUBLIC_API_URL=https://api.cloudiator.org`
- `ADMIN_SESSION_SECRET` (random, password manager)

```
You are implementing Cloudiator from this repo. Read PLAN.md, docs/cursor-settings.md, docs/next-steps.md, and the docs/ files. Do not skip RAM rules. Do not use Docker for Ollama. Do not put inference in Netlify. Work only on the current phase. Commit when the phase definition of done is met if I ask you to commit.

Phase A and B are green. Domain is cloudiator.org. API is https://api.cloudiator.org through named tunnel cloudiator-mini. Neon project cloudiator already has the schema. Dashboard hostname is app.cloudiator.org. Cloudflare Access is already on app.cloudiator.org. Do not scaffold apps/gateway/. Do not expose 11434. Do not run Ollama or LaunchAgents on this laptop.

Phase C only.

1. apps/dashboard Vite React. NO login form, NO shared admin password, NO Netlify Identity. Authentication is Cloudflare Access on app.cloudiator.org, configured outside the app. The app reads the Cf-Access-Authenticated-User-Email header in its server functions and trusts nothing else.
2. Create tenant, mint key, checkboxes for scopes from PLAN.md section 9 presets. Do not offer the speech preset; transcriptions are not implemented.
3. Show the key once. Next to the revoke button, state plainly that revocation takes up to 60 seconds to propagate (worker key cache).
4. Usage chart from Neon, reading the usage_daily rollup rather than raw events.
5. Download OpenAPI JSON for that key, with a separate "Salesforce (External Services)" button that hits ?target=salesforce.
6. Copy-paste Salesforce Named Credential + Apex snippet from docs/salesforce.md. The snippet must contain req.setTimeout(120000) and "stream": false.
7. A small browser chat playground that calls https://api.cloudiator.org/v1/chat/completions from the client with the minted key. No inference in Netlify functions, ever. DATABASE_URL is server-side only. The playground sends stream:false.
8. Netlify deploy. Custom domain app.cloudiator.org.
9. Tests: a build-output check that greps dist/ for neon.tech and fails if found.
```

**Prove it:** incognito on `app.cloudiator.org` is challenged by Cloudflare Access, not a password form. Mint a key, chat from the playground, see a usage row. `npm run build && grep -r neon.tech dist/` finds nothing.
