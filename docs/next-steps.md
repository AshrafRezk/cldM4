# Next steps — Phase E proven (2026-09-27)

**Phases A–E are proven on the Mini, and this commit puts D2–E on `main`.** #11 was squash-merged, so #12–#14 landed on their parent branches and not on `main`. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not pull `gpt-oss:20b`. Do not run FLUX 8-bit.

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

## Phase D2 proof (Mini, 2026-09-27)

The first `kickstart` returned before port 8080 was listening. After the worker logged `Application startup complete`, health stayed `idle_hot_9b`.

| Check | Result |
| --- | --- |
| `POST /v1/tools/query` fruit CSV, `SUM` by kind | `apples/5`, `pears/4`, `truncated: false` |
| `POST /v1/tools/chart` | `engine: matplotlib`, signed PNG URL on `https://api.cloudiator.org/artifacts/...` |
| Loaded models | `gemma4:e4b-it-qat`, `nomic-embed-text`. Swap 0. |

matplotlib, numpy, scipy, duckdb, and pyarrow are installed in the worker venv with `uv pip`.

## Phase D3 proof (Mini, 2026-09-27)

The first diagram call returned `not_supported`. Terminal had `/opt/homebrew/bin/dot`; the LaunchAgent PATH did not. The renderer now checks that path. After `git pull` and `kickstart`, health stayed `idle_hot_9b` with 388.4 GB free.

| Check | Result |
| --- | --- |
| `POST /v1/tools/text` `sf_id` `001D000000IRt53` | `001D000000IRt53IAD` |
| `POST /v1/tools/diagram` with `engine: mermaid` | `engine: graphviz`, signed PNG URL |
| Loaded models | `gemma4:e4b-it-qat`, `nomic-embed-text`. Swap 0. `dot` is `/opt/homebrew/bin/dot`. |

## Phase E happy path (Mini, 2026-09-27)

`Idempotency-Key: test-2` created job `dcbfbc7dc5af4e7e91967a7e5c057496` (202). It reached `succeeded` with artifact `8034c949723d4c1caca9c7838abfbb06`. `ollama ps` afterward was Gemma 5.4 GB and `nomic-embed-text` 370 MB, one generative model. Swap used went from 1707.88 MB to 1699.88 MB, so this generate did not add swap. `ok` stays false until a reboot clears the leftover swap from the 19.08 GB run.

## Phase E crash drill (Mini, 2026-09-27)

Job `1bf553e4641a47f29159da6f307e2317` was `running` when `mflux-generate` was killed. After 60 seconds, chat on `gemma4:e4b-it-qat` returned `Hi.` with no manual reload. `ollama ps` showed Gemma 5.4 GB and `nomic-embed-text` 370 MB. The job was `failed`. After `kickstart`, health was `idle_hot_9b` and that same job was still `failed`. Swap used was 1683.88 MB, down from 1699.88 MB before the drill.

Phase E is proven on the Mini. 8-bit stays off. `gpt-oss:20b` stays unpulled. `ok` stays false until a reboot clears the leftover swap from the 19.08 GB run.

## Next

On the Mini, from the repo root (the directory you are already in):

```bash
git checkout main
git pull origin main
launchctl kickstart -k gui/$UID/ai.cloudiator.worker
```

Do that only after this landing commit is on `main`. The worker venv already has the Phase D–E packages from the earlier branch. Phase F is the External Services import. It waits until you ask for it.

## Remaining

| When | What | Where |
| --- | --- | --- |
| After this commit is on `main` | Pull `main` and kickstart the worker | Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) and disable `cloudiator.netlify.app` | Neon + Netlify |
| When you ask | Phase F: External Services import of Salesforce OAS 3.0.3 | Salesforce |
