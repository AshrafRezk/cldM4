# Next steps — after laptop cloud setup (2026-09-20)

Laptop finished the cloud slice of Phase B. **Do not start the dashboard (Phase C) and do not create a Cloudflare Worker.** Inference stays on the Mini.

Secrets (Neon pooled URL, Zone ID, Access AUDs, team domain) live in the password manager, not this file. Checklist ticks: [operator-checklist.md](operator-checklist.md).

## Done on the laptop

- Domain `cloudiator.org` on Cloudflare Registrar, zone **Active**.
- Hostnames: `api.cloudiator.org`, `app.cloudiator.org`.
- Neon project `cloudiator` (AWS eu-west-2 London). `infra/neon.sql` applied. IP allowlist off.
- Bot Fight Mode **off**. Custom Skip rule `skip-sk-cld-salesforce` for `Bearer sk-cld-` on `api.cloudiator.org`.
- Cloudflare free rate-limit UI cannot key on Authorization / 60s — left empty; worker `rpm` will enforce.
- Access apps: `app.cloudiator.org` and `api.cloudiator.org/v1/admin` (not the whole API). Operator email allowed.
- Nominatim UA will be `Cloudiator/0.1 (ashrafrmattar@gmail.com)`.
- Repo: `infra/neon.sql`, OpenAPI fragments in `packages/schema`, cloudflared examples (placeholders only).

## This laptop, once

```bash
git push
```

Mini cannot `git pull` until this commit is on GitHub.

## Mini — Phase A (new chat, do this next)

Cursor **Pro Plus**. Agent mode. **Auto off.** Privacy Mode on. Model: **Claude Opus 5** (latest Opus). Attach `@PLAN.md` `@docs/cursor-phases.md`.

Before code:

- Ethernet, not Wi-Fi. Computer must not sleep.
- `uname -m` and Python 3.11 must print `arm64`. Abort on `x86_64`.
- Tick [operator-checklist.md](operator-checklist.md) §0 and exactly one boot policy in §6.
- Official **Ollama.app**, not `brew install ollama`.

Then paste **Phase A only** from [cursor-phases.md](cursor-phases.md). Definition of done: loopback chat + embeddings on `127.0.0.1:8080`, one uvicorn worker, at most one generative model in `ollama ps` (plus `nomic-embed-text`).

**Do not create the Cloudflare Tunnel until that is green.**

## Mini — Phase B remainder (new chat after A)

Named tunnel `cloudiator-mini` → `http://127.0.0.1:8080` only. `11434` must never appear in `~/.cloudflared/config.yml`.

Copy from the password manager into `~/Cloudiator/.env` (`chmod 600`, outside git): pooled `DATABASE_URL`, `PUBLIC_BASE_URL=https://api.cloudiator.org`, `CF_ACCESS_AUD` = **api** app AUD, `CF_ACCESS_TEAM_DOMAIN`, `NOMINATIM_USER_AGENT`.

Worker: key auth, 60s cache, rpm bucket, usage outbox, scoped OpenAPI. Prove from a **phone on cellular**, not house Wi-Fi.

## Later

| When | What |
| --- | --- |
| Phase C | Netlify dashboard on `app.cloudiator.org`. No inference in Functions. |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | Tools, OCR, maps. |
