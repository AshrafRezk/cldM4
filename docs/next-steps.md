# Next steps — after laptop cloud setup (2026-09-20)

Laptop finished the cloud slice of Phase B. **Phase A is already on `main`** (Gemma 4 E4B QAT worker). **Do not start the dashboard (Phase C) and do not create a Cloudflare Worker.** Inference stays on the Mini.

Secrets (Neon pooled URL, Zone ID, Access AUDs, team domain) live in the password manager, not this file. Checklist ticks: [operator-checklist.md](operator-checklist.md).

## Done

**Laptop:** `cloudiator.org` Active; `api.` / `app.`; Neon `cloudiator` in London with `infra/neon.sql`; WAF Skip `skip-sk-cld-salesforce`; Access on `app.cloudiator.org` and `api.cloudiator.org/v1/admin` only; Nominatim UA `Cloudiator/0.1 (ashrafrmattar@gmail.com)`.

**Mini (already on GitHub):** Phase A OpenAI shim, RAM scheduler, `gemma4:e4b-it-qat` + `nomic-embed-text`. Loopback worker on `127.0.0.1:8080`.

## This laptop, once

```bash
git push
```

Then on the Mini: `git pull`.

## Mini — Phase B (new chat, do this next)

Cursor **Pro Plus**. Agent mode. **Auto off.** Privacy Mode on. Model: **Claude Opus 5**. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md`.

Before the agent:

- `git pull`
- Confirm loopback still works: `curl -s http://127.0.0.1:8080/v1/health`
- Put password-manager values in `~/Cloudiator/.env` (`chmod 600`, **outside** git): pooled `DATABASE_URL` (`-pooler`), `PUBLIC_BASE_URL=https://api.cloudiator.org`, `CF_ACCESS_AUD` = **api** app AUD, `CF_ACCESS_TEAM_DOMAIN`, `NOMINATIM_USER_AGENT=Cloudiator/0.1 (ashrafrmattar@gmail.com)`
- Schema is already applied in Neon. Do not recreate tables unless the agent finds them missing.
- Tunnel name: `cloudiator-mini` → `http://127.0.0.1:8080` only. Never `11434`.

Paste the **shared opener** plus **Phase B only** from [cursor-phases.md](cursor-phases.md). Prove HTTPS from a **phone on cellular**.

## Later

| When | What |
| --- | --- |
| Phase C | Netlify dashboard on `app.cloudiator.org`. No inference in Functions. |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | Tools, OCR, maps. |
