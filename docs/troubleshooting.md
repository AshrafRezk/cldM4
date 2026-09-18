# Troubleshooting

Try these before changing architecture.

## Mini is slow / tokens per second near zero

Swap. Check Activity Monitor memory pressure (yellow/red) and `memory_pressure` in Terminal.

- Unload extra models: `ollama ps` then `ollama stop <name>`
- Confirm `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1`
- Do not run FLUX and 9B together
- Lower `num_ctx` to 4096
- Quit Chrome/Electron apps on the Mini if they eat 4GB+

## 401 invalid_api_key

- Key revoked or wrong `public_id`
- `Authorization` header missing `Bearer `
- Named Credential not sending the header (check External Credential)

## 403 scope_denied

Key lacks the capability. Check dashboard checkboxes vs the route (`tools.charts`, `image_generation`, etc.).

## 429 metal_busy / Retry-After

One Metal slot. Salesforce should switch to `POST /v1/jobs` instead of retry storms. Dashboard rpm may also fire.

## 503 or Cloudflare 502/504

- Worker not running: `launchctl list | grep cloudiator`
- Ollama down: `curl -s http://127.0.0.1:11434/api/tags`
- cloudflared down: `cloudflared tunnel info cloudiator-mini`
- Sync request longer than ~90–100s: use jobs
- Mini slept: Energy settings in host-setup.md

## Apex timeout at ~10s

Forgot `setTimeout(120000)`. Default is 10s.

## Nominatim 403 / HTML error page

Missing or generic User-Agent, or >1 req/s. Set `NOMINATIM_USER_AGENT` to an app name + contact email. Add a process-wide 1 rps lock.

## HEIC upload fails

`pillow-heif` not installed, or libheif missing. Re-run worker uv sync; test with an iPhone photo.

## QR decode fails

`brew install zbar` and reinstall `pyzbar` in the venv.

## Plotly PNG fails

Kaleido binary missing. Fall back to matplotlib Agg. Never fail the whole worker import on kaleido.

## Ollama works in app, FastAPI gets connection refused

`OLLAMA_HOST` must be `127.0.0.1:11434`. Do not use `0.0.0.0` in the worker URL. After changing LaunchAgent env, restart the Ollama app.

## Two models in `ollama ps`

keep_alive overlap. Set `OLLAMA_MAX_LOADED_MODELS=1` and `keep_alive=0` on exclusive jobs. Reload 9B after FLUX.

## Docker was installed “to help”

Remove it from the inference path. Metal does not pass through Docker Desktop usefully. Native Ollama.app only.

## Neon connection errors from Mini

Home ISP change, SSL, or sleeping laptop VPN. Test `psql $DATABASE_URL`. Usage writes must retry from local queue so chat still returns.

## Dashboard shows no usage

Worker cannot reach Neon; events stuck in Mini queue. Check worker.err log. Chat can still succeed.

## Tunnel hostname keeps changing

You used a quick tunnel. Recreate a **named** tunnel and CNAME.

## Port 11434 visible on WAN

Misconfigured ingress. cloudflared must point only at `http://127.0.0.1:8080`. Rotate all API keys if this ever happened.

## memory_pressure critical after OpenCV + 9B

Do not import `opencv-python` GUI wheel. Use headless. Unload 20B before large image batches.

## Salesforce heap error on image

You returned base64. Return `https://api.../artifacts/{id}?sig=...` instead.
