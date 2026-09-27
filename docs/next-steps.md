# Next steps — Phases A–E on main (2026-09-27)

**Phases A–E are proven on the Mini, and `main` matches that tree.** Health after the landing pull: `idle_hot_9b`, `gemma4:e4b-it-qat` and `nomic-embed-text` loaded, pressure normal, `degraded: ["swap_in_use"]` at 1643.88 MB. Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not pull `gpt-oss:20b`. Do not run FLUX 8-bit.

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

## If the Mac restarts

The dashboard (`app.cloudiator.org`, Netlify) and Neon stay up. Only the Mini's API goes quiet until a GUI session exists.

The worker (`ai.cloudiator.worker`) and the tunnel (`com.cloudiator.cloudflared`) are LaunchAgents with `RunAtLoad` and `KeepAlive`. They start themselves when the appliance user is logged into the GUI. They do not start at the FileVault pre-boot screen. Ollama.app is a GUI app: it starts on login only if it is in System Settings → General → Login Items. After it is up, the worker warms Gemma and `nomic-embed-text` by itself. A reboot clears the leftover swap, so `ok` can become true once those two models are loaded.

| How it stopped | What comes back |
| --- | --- |
| Apple menu → Restart, while you are logged in | The disk unlocks for that next boot. You still need the GUI login, unless automatic login is on. Then the two LaunchAgents start. Ollama starts if it is a login item. |
| Power cut, or a boot that stops at the FileVault password | Nothing starts until a person types the password. "Start up automatically after a power failure" only reaches that screen. |
| Planned reboot when nobody will be at the keyboard | `sudo fdesetup authrestart` unlocks the disk for exactly the next boot. The GUI login (or automatic login) is still required. |

Checklist §6 is still unticked, and automatic login is not recorded as enabled. Do not treat the Mini as unattended until one boot policy is chosen and a real reboot has been timed. After you log in, poll rather than kickstart:

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -sf http://127.0.0.1:8080/v1/health && echo && break
  sleep 3
done
```

Expect `idle_hot_9b`. If `loaded` stays empty, open Ollama and add it to Login Items.

## Still open

- [ ] Refresh the usage chart and confirm a `usage_daily` row for a playground chat. The nightly rollup is not scheduled, so a chat from today may not appear until `infra/neon-retention.sql` has run.
- [ ] Download both OpenAPI files (plain and `?target=salesforce`) from the dashboard.
- [ ] Confirm the on-screen Apex snippet contains `setTimeout(120000)` and `"stream": false`.
- [ ] Incognito on `https://app.cloudiator.org` is challenged by Cloudflare Access, not a password form.
- [ ] Disable `cloudiator.netlify.app`. It is not behind Access, so the email header can be spoofed there.
- [ ] Copy `ADMIN_SESSION_SECRET` into the password manager if a CLI log printed it.
- [ ] Tick exactly one boot policy in [operator-checklist.md](operator-checklist.md) §6, and confirm Ollama is a login item.
- [ ] Schedule `infra/neon-retention.sql`.

## Next code phase

Phase F waits until you ask. New Agent chat on the Mini, model **Claude Sonnet 5**, attach `@PLAN.md` `@docs/cursor-phases.md` `@docs/next-steps.md`, paste only the **Phase F only** block from [cursor-phases.md](cursor-phases.md). That phase is the Salesforce External Services import (OpenAPI 3.0.3, Apex `setTimeout(120000)`, `"stream": false`). Whisper large-v3-turbo is optional inside that phase and is not pulled.

Leave pull requests #3, #4, #7, #9, and #10. They conflict because that work is already on `main`.

## Remaining

| When | What | Where |
| --- | --- | --- |
| Before relying on a restart | Tick checklist §6 and confirm Ollama is a login item. Then reboot once and time `/v1/health` | Mini |
| After a playground chat | Confirm a `usage_daily` row. If today's chat is missing, the retention SQL is not scheduled yet | Neon |
| This week | Schedule `infra/neon-retention.sql` and disable `cloudiator.netlify.app` | Neon + Netlify |
| When you ask | Phase F: External Services import of Salesforce OAS 3.0.3 | Salesforce |
