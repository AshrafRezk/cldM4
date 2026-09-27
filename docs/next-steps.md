# Next steps — Phase E jobs (2026-09-27)

**Phases A–D3 are proven on the Mini.** Phase D is [PR #11](https://github.com/AshrafRezk/cldM4/pull/11). Phase D2 is [PR #12](https://github.com/AshrafRezk/cldM4/pull/12). Phase D3 is [PR #13](https://github.com/AshrafRezk/cldM4/pull/13). Phase E is this branch. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not pull `gpt-oss:20b`. Do not run FLUX 8-bit.

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

## Next

Merge [PR #11](https://github.com/AshrafRezk/cldM4/pull/11), then [#12](https://github.com/AshrafRezk/cldM4/pull/12), then [#13](https://github.com/AshrafRezk/cldM4/pull/13), in that order, when `main` should match the Mini.

Phase E warmup is recorded in [operator-checklist.md](operator-checklist.md) section 9. Production generates pass `--low-ram` and `--model ~/Cloudiator/models/flux-schnell-4bit --base-model schnell`. The worker does that itself. 8-bit stays off. `gpt-oss:20b` stays unpulled.

After the warmup the worker came back `idle_hot_9b` with Gemma (5.4 GB) and `nomic-embed-text` (370 MB). `ok` is false because `degraded` is `swap_in_use` (~1900 MB left over from the 19.08 GB run). Pressure is `normal`, so jobs are allowed. A reboot clears the leftover swap. It is not required before the first job.

```bash
cd /Users/ashrafrezk/cldM4
git fetch origin cursor/phase-e-flux-jobs-73f3
git checkout cursor/phase-e-flux-jobs-73f3
# MFLUX_MODEL_PATH defaults to ~/Cloudiator/models/flux-schnell-4bit.
# MFLUX_LOW_RAM defaults to true. Add them to ~/Cloudiator/.env if you want them explicit.
launchctl kickstart -k "gui/$(id -u)/ai.cloudiator.worker"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  curl -sf http://127.0.0.1:8080/v1/health && break
  sleep 2
done
echo
cd apps/worker
KEY=$(.venv/bin/python -m app.dbtool mint-key --tenant cloudiator --name 'phase-e' \
  --preset creative \
  | tee /dev/stderr | awk '/sk-cld-/{print $1; exit}')
cd ../..
JOB_JSON=$(curl -sS -D /tmp/job.hdr -o - http://127.0.0.1:8080/v1/jobs \
  -H "Authorization: Bearer $KEY" \
  -H 'Idempotency-Key: test-2' -H 'content-type: application/json' \
  -d '{"kind":"image","prompt":"a red bicycle"}')
echo "$JOB_JSON"
head -n 1 /tmp/job.hdr
JOB=$(printf '%s' "$JOB_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "job $JOB"
curl -sS -D /tmp/job2.hdr -o /tmp/job2.json http://127.0.0.1:8080/v1/jobs \
  -H "Authorization: Bearer $KEY" \
  -H 'Idempotency-Key: test-2' -H 'content-type: application/json' \
  -d '{"kind":"image","prompt":"a red bicycle"}'
head -n 1 /tmp/job2.hdr
cat /tmp/job2.json
echo
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do
  curl -sS http://127.0.0.1:8080/v1/jobs/$JOB -H "Authorization: Bearer $KEY"
  echo
  curl -sf http://127.0.0.1:8080/v1/jobs/$JOB -H "Authorization: Bearer $KEY" | grep -q '"status":"succeeded"' && break
  sleep 10
done
ollama ps
sysctl vm.swapusage
```

The first Mini job `5cccebb6053642da8f7506373c93f984` was 202, and the replay was 200 with that same id. mflux finished 4/4 and Gemma was reloaded. The job was marked failed because the worker created the output file first; mflux will not overwrite, so it saved `image_1.png` and the worker read the empty file. That is fixed. `Idempotency-Key: test-1` still returns the failed job for 24h. The retry uses `test-2`.

## Remaining

| When | What | Where |
| --- | --- | --- |
| When you want `main` to match the Mini | Merge PR #11, then #12, then #13 | GitHub, then Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| Now | Phase E checkout and the job curls above. Do not `pkill` mflux until the first job succeeds | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
