# Environment variables

Never commit real values. Mini: `~/Cloudiator/.env` or `apps/worker/.env`. Netlify: site env UI. Dashboard must not expose `DATABASE_URL` to the browser.

## Mini worker

| Name | Example | Required |
| --- | --- | --- |
| `CLOUDIATOR_ENV` | `production` | yes |
| `HOST` | `127.0.0.1` | yes |
| `PORT` | `8080` | yes |
| `PUBLIC_BASE_URL` | `https://api.example.com` | yes (artifact URLs) |
| `DATABASE_URL` | `postgresql://...neon.tech/neondb?sslmode=require` | yes from Phase B |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | yes |
| `DEFAULT_MODEL` | `qwen3.5:9b` | yes |
| `HEAVY_MODEL` | `gpt-oss:20b` | no |
| `EMBED_MODEL` | `nomic-embed-text` | yes |
| `NUM_CTX` | `4096` | yes |
| `MAX_TOKENS_DEFAULT` | `512` | yes |
| `ARTIFACT_DIR` | `/Users/<you>/Cloudiator/artifacts` | yes |
| `QUEUE_DB` | `/Users/<you>/Cloudiator/queue.db` | yes Phase E |
| `ARTIFACT_SIGNING_SECRET` | 32+ byte random | yes Phase E |
| `ADMIN_TOKEN` | random, LaunchAgent only | yes for /v1/admin |
| `LOG_PROMPTS_DEFAULT` | `false` | yes |
| `NOMINATIM_URL` | `https://nominatim.openstreetmap.org` | yes |
| `NOMINATIM_USER_AGENT` | `Cloudiator/0.1 (email@domain)` | **yes or Nominatim bans you** |
| `OVERPASS_URLS` | comma-separated mirrors | yes |
| `OSRM_URL` | `https://router.project-osrm.org` | yes |
| `GOOGLE_MAPS_API_KEY` | | no |
| `SLACK_WEBHOOK_URL` | | no (Mini down) |
| `MPLBACKEND` | `Agg` | yes |
| `HF_TOKEN` | | no |

Ollama-specific vars belong on the **Ollama LaunchAgent**, not only FastAPI (see host-setup).

## Netlify dashboard

| Name | Purpose |
| --- | --- |
| `DATABASE_URL` | Neon, server-only |
| `ADMIN_SESSION_SECRET` | cookie signing |
| `PUBLIC_API_URL` | `https://api.example.com` shown in snippets |

## Cloudflare

Tunnel UUID and credentials JSON live in `~/.cloudflared/` on the Mini. Do not put the JSON in git.

## Neon IP

If you enable Neon IP allowlisting, allow **the Mini egress IP** (home ISP may change — prefer Neon without allowlist or use a Cloudflare WARP/static later). Dashboard Netlify functions also need access (Neon “allow Netlify” is usually “allow all with SSL”).
