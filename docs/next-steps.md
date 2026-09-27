# Next steps — Phase D proven on the Mini (2026-09-27)

**Phases A, B, C, and D are done on the Mini.** The worker is on `cursor/phase-d-tools-ocr-maps-73f3`, health is `idle_hot_9b` (`gemma4:e4b-it-qat` + `nomic-embed-text`, swap 0), and playground CORS allows `https://app.cloudiator.org`. Phase D is not on `main` until [PR #11](https://github.com/AshrafRezk/cldM4/pull/11) is merged. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not start Phase E (`gpt-oss:20b` or FLUX) yet. The next build phase in [cursor-phases.md](cursor-phases.md) is Phase D2 (charts, stats, DuckDB).

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md).

## Done

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. Chat from the Air returned JSON 200. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords.

**Mini `.env`:** `NOMINATIM_USER_AGENT` is quoted. `DEFAULT_MODEL=gemma4:e4b-it-qat`. KEY=VALUE `.env` loader (do not `source` the file). `PUBLIC_BASE_URL=https://api.cloudiator.org` derives playground CORS as `https://app.cloudiator.org`.

**Dashboard (Phase C, live):** `https://app.cloudiator.org` on Netlify, Cloudflare Access only (no login form, no shared password). Landing at `/` (Agentforce-native product page + logo). Operator console at `/console` (tenants, scoped keys shown once, usage_daily, Salesforce OAS + Apex `setTimeout(120000)` / `"stream": false`, browser playground → Mini). `DATABASE_URL` is server-side only; `cd apps/dashboard && npm test` finds no `neon.tech` in `dist/`.

## Phase D proof (Mini, 2026-09-27)

| Check | Result |
| --- | --- |
| OCR `POST /v1/tools/ocr` on a large-font PNG | `{"text":"INVOICE 42"}` HTTP 200. No extra model loaded (`idle_hot_9b`). |
| Geocode `Cairo, Egypt` | `30.0443879, 31.2357257`. Second call `0.005s` (SQLite cache). |
| Chat-only key, `POST /v1/tools/ocr` | 403 |
| Signed artifact URL | 200 |
| Tampered signature | 404 |
| Path traversal | 404 |

`ocrmac` is installed in the worker venv (`uv pip`, not a `pip` binary). OCR passes a PIL image. `ARTIFACT_SIGNING_SECRET` is in `~/Cloudiator/.env`.

## Now

The two keys minted in that terminal were printed into this chat. Revoke them, then mint the real one from the console and leave the secret in the password manager.

```bash
cd /Users/ashrafrezk/cldM4/apps/worker
.venv/bin/python -m app.dbtool revoke-key ziwnk5ba8uvw
.venv/bin/python -m app.dbtool revoke-key 5rozejut8fkw
```

Mint the replacement at https://app.cloudiator.org/console (preset `salesforce_engineer`). Do not paste the secret back into chat.

## Remaining

| When | What | Where |
| --- | --- | --- |
| Now | Revoke the two public ids above and mint a replacement in the console | Mini |
| When you want `main` to match the Mini | Merge PR #11, then `git checkout main && git pull` and `scripts/install-launchagents.sh` | GitHub, then Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| **Phase D2** | Charts, stats, DuckDB. Next build phase. No new model. | Repo, then Mini |
| Phase E | FLUX jobs, and `gpt-oss:20b` only after D2/D3 and a disk check | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
