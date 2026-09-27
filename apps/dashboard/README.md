# Dashboard (Phase C)

Vite + React on Netlify. **No inference.** Chat from the playground goes to `https://api.cloudiator.org` in the browser. Neon is used only from Netlify functions.

Authentication is **Cloudflare Access** on `app.cloudiator.org`. This app has no login form, no shared admin password, and no Netlify Identity. Server functions read `Cf-Access-Authenticated-User-Email` and trust nothing else.

## Local

Do not run Ollama, LaunchAgents, or `scripts/mac-setup.sh` on this laptop.

```bash
cd apps/dashboard
cp .env.example .env          # pooled DATABASE_URL, PUBLIC_API_URL, ADMIN_SESSION_SECRET
npm ci
npx netlify dev               # Vite + functions; injects NETLIFY_DEV
```

`DEV_ACCESS_EMAIL` is honoured only under `netlify dev`. Production requires the Access header.

```bash
npm test                      # build, fail if dist/ contains neon.tech, unit tests
```

## Netlify env (site UI, never the browser bundle)

- `DATABASE_URL` — Neon **pooled** (`-pooler` in the host)
- `PUBLIC_API_URL=https://api.cloudiator.org`
- `ADMIN_SESSION_SECRET` — random, password manager

Disable the `*.netlify.app` default domain once `app.cloudiator.org` is attached, or anyone can spoof the Access email header against the naked origin.

## Mini CORS

The playground is a browser call. After deploying this branch, the Mini must `git pull` and restart the worker so `https://app.cloudiator.org` is allowed as an Origin (`DASHBOARD_ORIGIN` is derived from `PUBLIC_BASE_URL=https://api.cloudiator.org`).
