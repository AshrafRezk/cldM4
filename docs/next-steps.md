# Next steps — Mini pull, then Phase D (2026-09-27)

**Phases A, B, and C are done.** The dashboard at `https://app.cloudiator.org` is on `main`. Do not rebuild it. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions.

## Proven

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. Chat from the Air returned JSON 200. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords.

**Mini `.env`:** `NOMINATIM_USER_AGENT` is quoted. `DEFAULT_MODEL=gemma4:e4b-it-qat`. KEY=VALUE `.env` loader (do not `source` the file). `PUBLIC_BASE_URL=https://api.cloudiator.org` derives playground CORS as `https://app.cloudiator.org`.

**Dashboard (Phase C, live):** `https://app.cloudiator.org` on Netlify, Cloudflare Access only (no login form, no shared password). Landing at `/` (Agentforce-native product page + logo). Operator console at `/console` (tenants, scoped keys shown once, usage_daily, Salesforce OAS + Apex `setTimeout(120000)` / `"stream": false`, browser playground → Mini). `DATABASE_URL` is server-side only; `cd apps/dashboard && npm test` finds no `neon.tech` in `dist/`.

## Mini, this pull (required for playground CORS)

The laptop shipped worker CORS in this commit. Until the Mini pulls and restarts, the dashboard playground `Failed to fetch`s even with a valid key. Apex Named Credentials do not need CORS.

```bash
cd /path/to/cldM4
git checkout main
git pull origin main
# restart the worker so cors.py is loaded (PUBLIC_BASE_URL already implies app.cloudiator.org)
scripts/install-launchagents.sh
# or: launchctl kickstart -k gui/$UID/ai.cloudiator.worker
curl -sI -X OPTIONS https://api.cloudiator.org/v1/chat/completions \
  -H 'Origin: https://app.cloudiator.org' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control
```

Expect `Access-Control-Allow-Origin: https://app.cloudiator.org`. Do **not** run `ollama pull`, `scripts/mac-setup.sh`, or Docker.

## Still open

Landing Phase C did not close these operator checks:

- [ ] Refresh the usage chart and confirm a `usage_daily` row for a playground chat. The nightly rollup is still not scheduled, so a chat from today may not appear until `infra/neon-retention.sql` has run.
- [ ] Download both OpenAPI files (plain and `?target=salesforce`) from the dashboard.
- [ ] Confirm the on-screen Apex snippet contains `setTimeout(120000)` and `"stream": false`.
- [ ] Incognito on `https://app.cloudiator.org` is challenged by Cloudflare Access, not a password form.
- [ ] Disable `cloudiator.netlify.app`. It is not behind Access, so the email header can be spoofed there.
- [ ] Copy `ADMIN_SESSION_SECRET` into the password manager if a CLI log printed it.

## Remaining

| When | What | Where |
| --- | --- | --- |
| After this pull | Confirm playground chat from `app.cloudiator.org/console` returns JSON and a `usage_daily` row | Mini + browser |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) and disable `cloudiator.netlify.app` | Neon + Netlify |
| **Phase D (next chat)** | Tool registry, OCR (Vision), maps. Mini, Opus 5. Prompt in [cursor-phases.md](cursor-phases.md) | Mini |
| Phase E | `gpt-oss:20b` only after Phase D is green | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |

No speak model. No listen endpoint. Whisper large-v3-turbo is the planned listener (Phase F, not pulled). Gemma writes text. Kokoro-82M would speak English and seven other languages and does not speak Arabic; it is not in v1.

Phase D copy-paste: new Agent chat on the Mini, model **Claude Opus 5**, attach `@PLAN.md` `@docs/cursor-phases.md`, paste the **Phase D only** block from [cursor-phases.md](cursor-phases.md).
