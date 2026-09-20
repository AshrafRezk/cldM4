# Next steps — Phase C from the MacBook (2026-09-20)

**Phase A and B are proven.** Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions.

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md).

## Done

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. Chat from the Air returned JSON 200. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords. External Services import and the Neon-down drill are postponed (Phase F / later).

**Mini `.env`:** `NOMINATIM_USER_AGENT` is quoted. `DEFAULT_MODEL=gemma4:e4b-it-qat`.

**This branch (PR #8):** KEY=VALUE `.env` loader (do not `source` the file), `dbtool` reads `~/Cloudiator/.env`, embedder keep-alive via `/api/embed`, tunnel list JSON `null` is survivable, `--local` smoke skips the tunnel.

## This MacBook, once

Merge [PR #8](https://github.com/AshrafRezk/cldM4/pull/8) on GitHub, then:

```bash
cd /path/to/cldM4
git checkout main
git pull origin main
```

If #8 is still open and you want to start C anyway:

```bash
git fetch origin cursor/safe-env-source-5f2a
git checkout cursor/safe-env-source-5f2a
```

Do **not** run `ollama pull`, LaunchAgents, or `scripts/mac-setup.sh` on the Air.

## Phase C — Netlify dashboard (new chat, do this next)

Cursor **Pro Plus**. Agent mode. **Auto off.** Privacy Mode on. Model: **Claude Sonnet 5**. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md` `@docs/env.md`.

Netlify site env (server functions only, never the browser bundle):

- pooled `DATABASE_URL` (`-pooler` in the host)
- `PUBLIC_API_URL=https://api.cloudiator.org`
- `ADMIN_SESSION_SECRET` (random, password manager)

Cloudflare Access is already on `app.cloudiator.org`. No login form. No shared admin password. No Netlify Identity.

### Copy-paste into the MacBook Agent chat

```
You are implementing Cloudiator from this repo. Read PLAN.md, docs/cursor-settings.md, docs/next-steps.md, and the docs/ files. Do not skip RAM rules. Do not use Docker for Ollama. Do not put inference in Netlify. Work only on the current phase. Commit when the phase definition of done is met if I ask you to commit.

Phase A and B are green. Domain is cloudiator.org. API is https://api.cloudiator.org through named tunnel cloudiator-mini. Neon project cloudiator already has the schema. Dashboard hostname is app.cloudiator.org. Cloudflare Access is already on app.cloudiator.org. Do not scaffold apps/gateway/. Do not expose 11434. Do not run Ollama or LaunchAgents on this laptop.

Phase C only.

1. apps/dashboard Vite React. NO login form, NO shared admin password, NO Netlify Identity. Authentication is Cloudflare Access on app.cloudiator.org, configured outside the app. The app reads the Cf-Access-Authenticated-User-Email header in its server functions and trusts nothing else.
2. Create tenant, mint key, checkboxes for scopes from PLAN.md section 9 presets.
3. Show the key once. Next to the revoke button, state plainly that revocation takes up to 60 seconds to propagate (worker key cache).
4. Usage chart from Neon, reading the usage_daily rollup rather than raw events.
5. Download OpenAPI JSON for that key, with a separate "Salesforce (External Services)" button that hits ?target=salesforce.
6. Copy-paste Salesforce Named Credential + Apex snippet from docs/salesforce.md. The snippet must contain req.setTimeout(120000) and "stream": false.
7. A small browser chat playground that calls https://api.cloudiator.org/v1/chat/completions from the client with the minted key. No inference in Netlify functions, ever. DATABASE_URL is server-side only.
8. Netlify deploy. Custom domain app.cloudiator.org.
9. Tests: a build-output check that greps dist/ for neon.tech and fails if found.
```

**Prove it:** incognito on `app.cloudiator.org` is challenged by Cloudflare Access, not a password form. Mint a key, chat from the playground, see a usage row. `npm run build && grep -r neon.tech dist/` finds nothing.

## Later

| When | What |
| --- | --- |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | Tools, OCR, maps — Mini, Opus 5. |
| Phase F | External Services import of `/tmp/cloudiator-oas.json` (already valid 3.0.3). |
