# Troubleshooting

Try these before changing architecture.

## Salesforce gets HTML / `JSON.deserialize` throws / "Unexpected character '<'"

Cloudflare is challenging the callout. Apex is not a browser: it cannot run JavaScript or solve a challenge, so Bot Fight Mode, Browser Integrity Check, Turnstile, or "I'm Under Attack" turn every org's traffic into an interstitial page.

```bash
curl -s -A 'Salesforce/1.0' -o /tmp/r.txt -w '%{http_code}\n' https://api.<domain>/v1/health
head -c 200 /tmp/r.txt      # JSON = good. <!DOCTYPE html = the WAF is eating you.
```

Fix: the zone settings and WAF skip rule in `PLAN.md` §13 / `docs/operator-checklist.md` §2. This is the most common Phase F failure.

## Mini is slow / tokens per second near zero

Swap. Check `sysctl vm.swapusage` (used must be 0.00M) and `sysctl -n kern.memorystatus_vm_pressure_level` (1 = normal).

- `ollama ps`, then `ollama stop <name>` on anything unexpected
- Confirm `OLLAMA_MAX_LOADED_MODELS=2` and `OLLAMA_NUM_PARALLEL=1` — **not 4**
- `pgrep -fc "uvicorn app.main:app"` must be **1**. More than one means `--workers > 1` and two schedulers each loading models
- Do not run FLUX and the chat model together
- Lower `num_ctx` to 4096
- Quit Chrome/Electron apps on the Mini. A stray `mmdc` Chromium is 0.4–1.2 GB

## Chat is randomly cold and slow, but only sometimes

Embeddings are evicting the chat model. `OLLAMA_MAX_LOADED_MODELS` is `1`; it must be `2` (slot 1 = one generative model, slot 2 = `nomic-embed-text`). See `PLAN.md` §4.

If the chat model unloads after a quiet half hour, the worker is omitting `keep_alive` and inheriting `OLLAMA_KEEP_ALIVE=30m`. The worker must send `keep_alive: -1` explicitly on every hot-model call.

## The hot Gemma never comes back after an image or 20B job

The exclusive teardown is not in a `finally`, so a crash left the lock held and no model loaded. Symptoms: everything returns `429 metal_busy` and `ollama ps` is empty.

Immediate: restart the worker (`launchctl kickstart -k gui/$UID/ai.cloudiator.worker`).
Real fix: `PLAN.md` §8, exclusive slot contract — `async with metal_lock`, kill orphan subprocesses, reload the hot model in `finally`, plus the 30s watchdog. Prove it with the Phase E crash drill (`pkill -9 -f mflux`).

## 401 invalid_api_key

- Key revoked, or wrong `public_id`
- `Authorization` header missing the `Bearer ` prefix
- You just revoked or minted a key: the worker caches lookups for **60 seconds**. Wait, or `POST /v1/admin/cache/flush`
- **Works in `curl` but 401 from Apex:** the running user has no permission set granting access to the External Credential *principal*. This is the single most common Named Credential failure and nothing in the error says so. See `docs/salesforce.md`

## 403 scope_denied

Key lacks the capability. Check dashboard checkboxes against the route (`tools.charts`, `image_generation`, etc.). Note that scope is re-checked on **every** tool call inside a chat loop, so a model that invents a tool name gets a 403 tool result mid-conversation — that is correct behaviour, not a bug.

## 429 metal_busy / Retry-After

One Metal slot. Salesforce should switch to `POST /v1/jobs` rather than retry storms. The per-key `rpm` bucket and the Cloudflare rate-limit rule can also fire.

## 429 disk_full

Free disk is under `MIN_FREE_DISK_GB`. Check the artifact janitor is running and `ARTIFACT_TTL_HOURS` is set; check log rotation (`newsyslog`); check whether a full-precision FLUX download landed in `~/.cache/huggingface` (that is ~34 GB you probably do not need — see `PLAN.md` §7).

```bash
df -h /
du -sh ~/.cache/huggingface ~/.ollama ~/Cloudiator/artifacts ~/Cloudiator/logs
```

## 503 or Cloudflare 502/504/524

- Worker not running: `launchctl print gui/$UID/ai.cloudiator.worker | head -20`
- Ollama down: `curl -s http://127.0.0.1:11434/api/tags`
- cloudflared down: `cloudflared tunnel info cloudiator-mini`
- **524 specifically** means the request passed ~100s at Cloudflare. The worker must return its own error at 90s; if you are seeing 524s, something is running past the deadline — usually an uncapped tool loop. Check `MAX_TOOL_ITERATIONS` and `TOOL_LOOP_BUDGET_SECONDS`
- Mini slept: Energy settings in host-setup.md

## Mini is at the login screen after a power cut

FileVault. A cold boot stops at the pre-boot unlock screen, so there is no user session, so no LaunchAgent runs and Ollama.app never starts. "Start up automatically after a power failure" only gets you to that screen.

Somebody has to type the password. For planned reboots use `sudo fdesetup authrestart`, which unlocks the disk for exactly the next boot. Decide the policy in `docs/operator-checklist.md` §6 and make sure the health webhook is what tells you, not a user.

## Apex timeout at ~10s

Forgot `setTimeout(120000)`. Default is 10s.

## Nominatim 403 / HTML error page

Missing or generic User-Agent, or more than 1 req/s. Set `NOMINATIM_USER_AGENT` to an app name plus a real contact email, and use a process-wide 1 rps lock on cache **misses**. If a chat loop is geocoding lists, the geocode cache is not working — check `GEOCODE_CACHE_DB`. A block lands on your home IP and takes out everything else on that connection.

## `python3.11` is x86_64 / `import Vision` fails / mlx will not install

Rosetta. `uname -m` must be `arm64`, and so must `python3.11 -c "import platform; print(platform.machine())"`. Uncheck "Open using Rosetta" on Terminal.app, reinstall Homebrew natively, rebuild the venv.

If the machine is arm64 but `pyobjc` Vision fails at runtime with a framework complaint, rebuild the venv against Homebrew's framework Python: `uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11`.

## HEIC upload fails

`pillow-heif` not installed, or libheif missing. Re-run worker `uv sync`; test with a real iPhone photo.

## QR decode fails

`brew install zbar` and reinstall `pyzbar` in the venv.

## Plotly PNG fails

Kaleido binary missing. Fall back to matplotlib Agg. Never fail worker import or the whole request on kaleido.

## Mermaid renders leave Chromium processes behind

`mmdc` spawns a headless Chromium per render and orphans it on timeout. Kill the process tree, not the parent. If this keeps happening, set `ENABLE_MERMAID=false` — Graphviz is the default renderer and the fallback. `pgrep -fl chrome` should be empty when nothing is rendering.

## Ollama works in the app, FastAPI gets connection refused

`OLLAMA_HOST` must be `127.0.0.1:11434`. Do not use `0.0.0.0` in the worker URL. After changing LaunchAgent env, restart the Ollama app.

Also check for a second install: `brew list | grep -i ollama`. Two servers fight over the port, and if the brew one wins it runs **without** your environment, so `OLLAMA_MAX_LOADED_MODELS` is unset and the RAM rules silently stop applying.

## Two generative models in `ollama ps`

The scheduler skipped the unload-and-verify before an exclusive load. It must `keep_alive=0` the hot model and then **poll `/api/ps`** until only `nomic-embed-text` remains — never assume the stop took effect. `nomic-embed-text` plus one generative model is expected and fine.

## `cloudflared` cannot reach the worker, but `curl` on the Mini can

macOS Sequoia Local Network permission. A process first launched by `launchd` can be denied with no visible prompt. Run `cloudflared tunnel run cloudiator-mini` once interactively in Terminal, approve the prompt, and check System Settings → Privacy & Security → Local Network.

## Docker was installed "to help"

Remove it from the inference path. Metal does not pass through Docker Desktop usefully. Native Ollama.app only.

## Neon connection errors from the Mini

Neon computes auto-suspend when idle and drop connections; a pooled connection held for days goes stale. Check pool settings (max 2, pre-ping on, 300s recycle) and that you are using the `-pooler` endpoint. Test with `psql $DATABASE_URL`.

A chat with a cached key must still succeed with Neon completely down — if it does not, auth is not falling back to the key cache.

## Dashboard shows no usage

Worker cannot reach Neon; events are sitting in the outbox. Check `outbox_depth` in `/v1/health` and `worker.err`. Chat still succeeds — that is by design. Also confirm the nightly rollup into `usage_daily` is running, since the dashboard reads the rollup.

## The health check pages at 3am but the Mini is fine

Somebody added a database call to `/v1/health`. It must be local-only and return 200 with `"db": "degraded"` when Neon is suspended. Deep checks belong in `/v1/health/deep` behind Cloudflare Access.

## Tunnel hostname keeps changing

You used a quick tunnel. Recreate a **named** tunnel and CNAME.

## Port 11434 visible on WAN

Misconfigured ingress. `grep -c 11434 ~/.cloudflared/config.yml` must be 0, and cloudflared must point only at `http://127.0.0.1:8080`. If this ever happened, rotate all API keys and assume the models were driven by strangers.

## memory_pressure critical after OpenCV + chat model

Do not import the `opencv-python` GUI wheel — headless only. Unload the heavy model before large image batches, and make sure Chromium-backed renderers take `cpu_heavy_lock` (`PLAN.md` §8 rule 7) instead of running alongside an exclusive job.

## Salesforce heap error on image

You returned base64. Return an artifact id and a signed URL instead. `max_response_bytes` on the key should be preventing this server-side.

## A stored artifact link is dead

Signed URLs expire (default 15 minutes). Store the artifact **id** on the record, not the URL, and re-mint with `POST /v1/artifacts/{id}/sign`. If the artifact itself is gone, it aged out of `ARTIFACT_TTL_HOURS` — re-run the job.

Also check the clock: signature expiry is absolute time, and a drifting clock 404s valid links. Date & Time → set automatically.

## The model confidently answers the wrong question

Context truncation. Ollama silently drops the oldest tokens past `num_ctx`. The worker should be estimating prompt tokens and returning `400 context_length_exceeded` first. If a vision request triggers it, check the image downscale (long edge 1024, max 4 images) — a full-resolution phone photo is thousands of tokens on its own.

## Duplicate FLUX jobs from one Salesforce action

Apex retried a timed-out callout. Send an `Idempotency-Key` header on `POST /v1/jobs`.

## Arabic comes back in English, or the model is huge and the box swaps

Wrong Ollama tag. `gemma4` / `gemma4:latest` / `gemma4:e4b` is the **9.6 GB Q4_K_M**, not the QAT Q4_0 default. `DEFAULT_MODEL` must be `gemma4:e4b-it-qat` (~6.1 GB) or, if you measured swap = 0, `gemma4:12b-it-qat` (~7.2 GB). Never `26b` / `31b` / `*-q8_0` / `*-bf16`.

```bash
ollama show "$DEFAULT_MODEL" | head
# file type should be Q4_0 for the QAT tags
```

If the tag is right and replies are still English-only, the worker may be injecting a system prompt that says "respond in English", or `GEMMA_THINKING=true` is eating `max_tokens` before the Arabic answer. Both are bugs.

Gemma 4 **does not generate images**. "Generate a picture" is FLUX (Phase E). "What does this Arabic invoice say?" is OCR first, then Gemma vision.
