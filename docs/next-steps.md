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

## Phase E happy path (Mini, 2026-09-27)

`Idempotency-Key: test-2` created job `dcbfbc7dc5af4e7e91967a7e5c057496` (202). It reached `succeeded` with artifact `8034c949723d4c1caca9c7838abfbb06`. `ollama ps` afterward was Gemma 5.4 GB and `nomic-embed-text` 370 MB, one generative model. Swap used went from 1707.88 MB to 1699.88 MB, so this generate did not add swap. `ok` stays false until a reboot clears the leftover swap from the 19.08 GB run.

## Next: crash drill

`$KEY` has to be minted in this terminal. The drill starts a second image, kills `mflux-generate` once the job is `running`, waits 60s, then chats. Chat has to answer with no manual model reload. After that, a worker restart must still return that same job.

```bash
cd /Users/ashrafrezk/cldM4/apps/worker
KEY=$(.venv/bin/python -m app.dbtool mint-key --tenant cloudiator --name 'phase-e-crash' \
  --preset creative \
  | tee /dev/stderr | awk '/sk-cld-/{print $1; exit}')
cd /Users/ashrafrezk/cldM4
test -n "$KEY" || { echo 'key was not minted'; exit 1; }
JOB_JSON=$(curl -sS http://127.0.0.1:8080/v1/jobs \
  -H "Authorization: Bearer $KEY" \
  -H 'Idempotency-Key: crash-1' -H 'content-type: application/json' \
  -d '{"kind":"image","prompt":"a red bicycle"}')
echo "$JOB_JSON"
CRASH=$(printf '%s' "$JOB_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  STATUS=$(curl -sf http://127.0.0.1:8080/v1/jobs/$CRASH -H "Authorization: Bearer $KEY" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "status $STATUS"
  test "$STATUS" = "running" && break
  sleep 2
done
pkill -9 -f mflux-generate || echo 'mflux was already gone'
sleep 60
curl -sS http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model":"gemma4:e4b-it-qat","messages":[{"role":"user","content":"Say hi in one word."}],"max_tokens":16,"stream":false}'
echo
ollama ps
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  STATUS=$(curl -sf http://127.0.0.1:8080/v1/jobs/$CRASH -H "Authorization: Bearer $KEY" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "after-kill $STATUS"
  test "$STATUS" = "failed" -o "$STATUS" = "succeeded" && break
  sleep 5
done
launchctl kickstart -k "gui/$(id -u)/ai.cloudiator.worker"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  curl -sf http://127.0.0.1:8080/v1/health && break
  sleep 2
done
echo
curl -sS http://127.0.0.1:8080/v1/jobs/$CRASH -H "Authorization: Bearer $KEY"
echo
```

The chat JSON has to contain a one-word reply. `ollama ps` has to show Gemma. After the restart, `$CRASH` has to still be `failed` (or `succeeded` if the kill missed it), not `queued`. This key cannot see the earlier succeeded job; that row belongs to the key minted in the previous terminal.

## Remaining

| When | What | Where |
| --- | --- | --- |
| When you want `main` to match the Mini | Merge PR #11, then #12, then #13 | GitHub, then Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| Now | Crash drill: kill `mflux-generate` mid-job, then chat within 60s, then restart and read the succeeded job | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
