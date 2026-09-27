# Next steps — Mini pull, then Phase D (2026-09-27)

**Phases A, B, and C are done.** Phase D (tool registry, Apple Vision OCR, maps) is the code on branch `cursor/phase-d-tools-ocr-maps-73f3`. It is not on the Mini until that branch is pulled. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions.

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md).

## Done

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

## Remaining

| When | What | Where |
| --- | --- | --- |
| After this pull | Confirm playground chat from `app.cloudiator.org/console` returns JSON and a `usage_daily` row | Mini + browser |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| **Phase D** | Tool registry, OCR (Vision), maps. Code is in `cursor/phase-d-tools-ocr-maps-73f3`. Prove it on the Mini: OCR does not change `ollama ps`, a repeated geocode makes no second Nominatim call, an unscoped key is 403. Vision does not run on Linux. | Mini |
| Phase E | `gpt-oss:20b` only after Phase D is green | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |

Phase D is already implemented on `cursor/phase-d-tools-ocr-maps-73f3`. On the Mini, pull that branch after the CORS restart above and run the Phase D proof commands in [cursor-phases.md](cursor-phases.md). Do not start a second Phase D implementation.
