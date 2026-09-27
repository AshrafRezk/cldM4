# Next steps — Phase D3 on the Mini (2026-09-27)

**Phases A–D2 are proven on the Mini.** Phase D3 (image ops, documents, diagrams) is this branch, `cursor/phase-d3-image-docs-diagrams-73f3`. It is not on the Mini until that branch is checked out. Phase D is [PR #11](https://github.com/AshrafRezk/cldM4/pull/11). Phase D2 is [PR #12](https://github.com/AshrafRezk/cldM4/pull/12). Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not start Phase E (`gpt-oss:20b` or FLUX).

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

## Mini, now (Phase D3)

`salesforce_engineer` already includes `tools.image_ops`, `tools.docs`, `tools.text`, and `tools.time`. Diagrams need `tools.diagrams` (the creative preset, or pass `--capabilities` ). Graphviz (`dot`) must be on the Mini; `scripts/mac-setup.sh` installs it, and `brew install graphviz` is enough if `dot` is missing. Do not run `mac-setup` again just for that.

The first Mini run converted `001D000000IRt53` to `001D000000IRt53IAD`. The diagram call returned `not_supported` because launchd's PATH is `/usr/bin:/bin:/usr/sbin:/sbin`, so the worker could not see `/opt/homebrew/bin/dot` even though Terminal could. The handler now checks that path (and `/usr/local/bin/dot`) itself. Pull and kickstart; do not reinstall the LaunchAgent.

Wait for `/v1/health` after `kickstart`. The last restart returned before port 8080 was open.

```bash
cd /Users/ashrafrezk/cldM4
git fetch origin cursor/phase-d3-image-docs-diagrams-73f3
git checkout cursor/phase-d3-image-docs-diagrams-73f3
git pull --ff-only
command -v dot >/dev/null || brew install graphviz
launchctl kickstart -k "gui/$(id -u)/ai.cloudiator.worker"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  curl -sf http://127.0.0.1:8080/v1/health && break
  sleep 1
done
echo
```

Then, with `KEY` set to a `salesforce_engineer` key and `DIAGRAM_KEY` set to a key that has `tools.diagrams`:

```bash
curl -sS http://127.0.0.1:8080/v1/tools/text -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  -d '{"action":"sf_id","id":"001D000000IRt53"}'

curl -sS http://127.0.0.1:8080/v1/tools/diagram -H "Authorization: Bearer $DIAGRAM_KEY" \
  -H 'content-type: application/json' \
  -d '{"source":"digraph { apples -> pears }","engine":"mermaid"}'
```

Expect `id18` of `001D000000IRt53IAD`, and a diagram `engine` of `graphviz` (mermaid is off) whose `url` opens as a PNG. `ollama ps` stays on the hot model and the embedder.

## Remaining

| When | What | Where |
| --- | --- | --- |
| Now | The Phase D3 checkout and the two curls above | Mini |
| When you want `main` to match the Mini | Merge PR #11, then #12, then this branch | GitHub, then Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| Phase E | FLUX jobs, and `gpt-oss:20b` only after a disk check | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
