# Next steps — Phase D on the Mini (2026-09-27)

**Phases A, B, and C are done.** The Mini is on `main` (`d9d4162`), the worker LaunchAgent is running, and the playground CORS preflight returns `Access-Control-Allow-Origin: https://app.cloudiator.org`. Phase D (tool registry, Apple Vision OCR, maps) is the code on branch `cursor/phase-d-tools-ocr-maps-73f3`. It is not on the Mini until that branch is checked out. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions.

Secrets stay in the password manager, not this file. Checklist: [operator-checklist.md](operator-checklist.md).

## Done

**API:** `https://api.cloudiator.org` → named tunnel `cloudiator-mini` (`e88624cb-3f03-4578-a38b-a7e3e090c873`) → `http://127.0.0.1:8080`. Gemma 4 E4B QAT + `nomic-embed-text`. Chat from the Air returned JSON 200. A garbage key is a FastAPI JSON 401, not Cloudflare HTML. `:11434` times out on the WAN. Salesforce OAS is OpenAPI `3.0.3` with zero composition keywords.

**Mini `.env`:** `NOMINATIM_USER_AGENT` is quoted. `DEFAULT_MODEL=gemma4:e4b-it-qat`. KEY=VALUE `.env` loader (do not `source` the file). `PUBLIC_BASE_URL=https://api.cloudiator.org` derives playground CORS as `https://app.cloudiator.org`.

**Dashboard (Phase C, live):** `https://app.cloudiator.org` on Netlify, Cloudflare Access only (no login form, no shared password). Landing at `/` (Agentforce-native product page + logo). Operator console at `/console` (tenants, scoped keys shown once, usage_daily, Salesforce OAS + Apex `setTimeout(120000)` / `"stream": false`, browser playground → Mini). `DATABASE_URL` is server-side only; `cd apps/dashboard && npm test` finds no `neon.tech` in `dist/`.

## Mini, now (Phase D)

`main` does not contain the tool routes. Check out the Phase D branch, install the two packages the existing venv does not have yet (`python-multipart` for the OCR upload, `ocrmac` for Apple Vision), then restart. Do **not** run `ollama pull`, `scripts/mac-setup.sh`, or Docker.

```bash
cd /Users/ashrafrezk/cldM4
git fetch origin cursor/phase-d-tools-ocr-maps-73f3
git checkout cursor/phase-d-tools-ocr-maps-73f3
# uv venvs have no pip binary. Install into the worker venv with uv.
cd apps/worker && uv pip install 'python-multipart>=0.0.9' 'ocrmac>=1.0' && cd ../..
# ARTIFACT_SIGNING_SECRET must be set in ~/Cloudiator/.env (32+ random bytes).
# Generate once if the line is missing; do not commit it:
#   printf 'ARTIFACT_SIGNING_SECRET=%s\n' "$(openssl rand -hex 32)" >> ~/Cloudiator/.env
scripts/install-launchagents.sh
curl -s http://127.0.0.1:8080/v1/health
```

Mint a key in https://app.cloudiator.org/console (preset `salesforce_engineer` already includes `tools.ocr` and `tools.maps`). Put it in `KEY`. For the 403 check, mint a second key with only `chat` and put it in `NO_OCR_KEY`.

```bash
# OCR loads no extra weights. Use any small PNG.
ollama ps > /tmp/before.txt
curl -s -F file=@screenshot.png http://127.0.0.1:8080/v1/tools/ocr \
  -H "Authorization: Bearer $KEY" | jq .text
ollama ps > /tmp/after.txt && diff /tmp/before.txt /tmp/after.txt

# Cache: second Cairo lookup is <50ms and makes no new Nominatim call.
curl -s http://127.0.0.1:8080/v1/tools/geocode -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' -d '{"q":"Cairo, Egypt"}' | jq
curl -s -o /dev/null -w 'second %{time_total}s\n' http://127.0.0.1:8080/v1/tools/geocode \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"q":"Cairo, Egypt"}'

# unscoped key
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/v1/tools/ocr \
  -H "Authorization: Bearer $NO_OCR_KEY"
```

Expect: `diff` prints nothing, the second geocode is under 50ms, the unscoped key prints `403`. Full contract: [cursor-phases.md](cursor-phases.md) Phase D. Do not start a second Phase D implementation. Do not start Phase E.

## Remaining

| When | What | Where |
| --- | --- | --- |
| Now | The Phase D checkout and proof block above | Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, `infra/neon-retention.sql` is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage) | Neon |
| Phase E | `gpt-oss:20b` only after Phase D is green | Mini |
| Phase F | External Services import of Salesforce OAS 3.0.3 | Salesforce |
