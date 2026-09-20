# Next steps — after laptop cloud setup (2026-09-20)

Laptop finished the cloud slice of Phase B. **Phase A is already on `main`** (Gemma 4 E4B QAT worker). **Do not start the dashboard (Phase C) and do not create a Cloudflare Worker.** Inference stays on the Mini.

Secrets (Neon pooled URL, Zone ID, Access AUDs, team domain) live in the password manager, not this file. Checklist ticks: [operator-checklist.md](operator-checklist.md).

## Done

**Laptop:** `cloudiator.org` Active; `api.` / `app.`; Neon `cloudiator` in London with `infra/neon.sql`; WAF Skip `skip-sk-cld-salesforce`; Access on `app.cloudiator.org` and `api.cloudiator.org/v1/admin` only; Nominatim UA `Cloudiator/0.1 (ashrafrmattar@gmail.com)`.

**Mini (already on GitHub):** Phase A OpenAI shim, RAM scheduler, `gemma4:e4b-it-qat` + `nomic-embed-text`. Loopback worker on `127.0.0.1:8080`.

**Phase B code (on GitHub, not yet proven on this Mini):** key auth with argon2id and the 60s cache, the Neon client, the usage outbox, per-key OpenAPI including the Salesforce 3.0.3 variant, Access-verified `/v1/admin/*`, and the tunnel installer. What is left is the Mini-side run order below and the human proofs at the end of it.

## This laptop, once

```bash
git push
```

Then on the Mini: `git pull`.

## If `.env:59: parse error near '('`

That is `NOMINATIM_USER_AGENT`. Quote it, then restart — do not `source` the file. Details: [troubleshooting.md](troubleshooting.md). The key you already minted is fine.

```bash
# in ~/Cloudiator/.env, the line must be:
# NOMINATIM_USER_AGENT="Cloudiator/0.1 (ashrafrmattar@gmail.com)"

tail -40 ~/Cloudiator/logs/worker.err
launchctl kickstart -k gui/$UID/ai.cloudiator.worker
sleep 8
curl -s http://127.0.0.1:8080/v1/health | jq
# then: export SMOKE_API_KEY=sk-cld-... and scripts/smoke-phase-b.sh --local
# then the tunnel steps below
```

## Mini — Phase B (new chat, do this next)

Cursor **Pro Plus**. Agent mode. **Auto off.** Privacy Mode on. Model: **Claude Opus 5**. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md`.

Before the agent:

- `git pull`
- Confirm loopback still works: `curl -s http://127.0.0.1:8080/v1/health`
- Put password-manager values in `~/Cloudiator/.env` (`chmod 600`, **outside** git): pooled `DATABASE_URL` (`-pooler`), `PUBLIC_BASE_URL=https://api.cloudiator.org`, `CF_ACCESS_AUD` = **api** app AUD, `CF_ACCESS_TEAM_DOMAIN`, `ADMIN_TOKEN`, `NOMINATIM_USER_AGENT="Cloudiator/0.1 (ashrafrmattar@gmail.com)"` (the quotes are required — unquoted parentheses are a zsh parse error)
- Schema is already applied in Neon. Do not recreate tables unless the agent finds them missing.
- Tunnel name: `cloudiator-mini` → `http://127.0.0.1:8080` only. Never `11434`.

Prove HTTPS from a **phone on cellular**.

### Phase B run order on the Mini

The code for Phase B is on `main`; these are the steps that touch this machine and the Cloudflare account.

```bash
cd apps/worker && uv sync --extra dev && cd -     # asyncpg, argon2-cffi, pyjwt
scripts/apply-neon-schema.sh                      # verifies first; applies only what is missing
launchctl kickstart -k gui/$UID/ai.cloudiator.worker

cd apps/worker && .venv/bin/python -m app.dbtool mint-key \
  --tenant cloudiator --name 'Phase B smoke' --preset salesforce_engineer && cd -
# the plaintext key is printed once; put it in the password manager
# the CLI reads ~/Cloudiator/.env itself — do not `source` that file in zsh

cloudflared tunnel login                          # browser, by hand, zone must be Active
cloudflared tunnel run cloudiator-mini            # ONCE interactively: Local Network prompt, then Ctrl-C
scripts/install-tunnel.sh                         # config + DNS + LaunchAgent

export SMOKE_API_KEY=sk-cld-...
scripts/smoke-phase-b.sh
```

Then the three things no script can do for you: repeat the HTTPS checks from a **phone on cellular**, import `GET /v1/openapi.json?target=salesforce` into External Services in a dev org, and run the Neon-down drill (block the Neon host, confirm chat still returns 200 on a cached key, `db` goes `degraded`, `outbox_depth` grows, then unblock and watch it drain).

Tick `docs/operator-checklist.md` §2 (tunnel UUID, DNS, WAF skip verified) and §3 (retention scheduled) as you go.

### Copy-paste into the Mini Agent chat

New chat. Agent. Opus 5. Auto off. Attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md`. Paste **everything** in the block below:

```
You are implementing Cloudiator from this repo. Read PLAN.md, docs/cursor-settings.md, docs/next-steps.md, and the docs/ files. Do not skip RAM rules. Do not use Docker for Ollama. Do not put inference in Netlify. Work only on the current phase. Commit when the phase definition of done is met if I ask you to commit.

Phase A is already green on this Mini (gemma4:e4b-it-qat). Domain is cloudiator.org. Neon project cloudiator already has infra/neon.sql applied. Pooled DATABASE_URL, CF_ACCESS_AUD (the api app), CF_ACCESS_TEAM_DOMAIN, and NOMINATIM_USER_AGENT belong in ~/Cloudiator/.env (chmod 600, outside git). Do not recreate the Neon project or tables unless they are missing. Do not scaffold apps/gateway/. Do not expose 11434.

Phase B only. Do not start the dashboard UI except a stub if needed.

1. Apply docs/schema.md to Neon. Put the POOLED DATABASE_URL in the Mini .env (chmod 600, never commit).
2. Neon client config per PLAN.md section 11: pool min 0 / max 2, pre-ping, 300s recycle, 3s connect timeout, 5s statement timeout. Neon must never be on the critical path of a chat response.
3. API keys: mint sk-cld-{public_id}_{secret}, argon2id with time_cost=2, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16. Look up by public_id, constant-time verify. 401/403/429 in OpenAI error shape.
4. Cache key lookups 60s (positive and negative) so argon2id is off the hot path. Add POST /v1/admin/cache/flush. Strip Authorization from every log path including exception handlers.
5. Per-key rpm token bucket in-process, 429 + Retry-After.
6. usage_outbox in the Mini SQLite: write locally, flush to Neon every 10s in batches of 500, cap 100k rows dropping oldest, expose outbox_depth in /v1/health. A chat must succeed with Neon completely down.
7. Named Cloudflare Tunnel to http://127.0.0.1:8080 only, config from docs/host-setup.md, no-autoupdate true. No quick tunnels. 11434 must never appear in the ingress. Tunnel name cloudiator-mini. Hostname api.cloudiator.org.
8. GET /v1/openapi.json filtered by key scopes, plus ?target=salesforce emitting the restricted OpenAPI 3.0.3 subset from PLAN.md section 10. Reuse packages/schema if present.
9. /v1/admin/* verifies the Cf-Access-Jwt-Assertion JWT against the Access JWKS and CF_ACCESS_AUD. ADMIN_TOKEN is accepted only for requests arriving on loopback.
10. Tests: apps/worker/tests/test_auth.py, test_key_cache.py, test_usage_outbox.py, test_openapi_filter.py, scripts/smoke-phase-b.sh.
```

## Later

| When | What |
| --- | --- |
| Phase C | Netlify dashboard on `app.cloudiator.org`. No inference in Functions. |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | Tools, OCR, maps. |
