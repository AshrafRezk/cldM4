# Next steps — after Phase C deploy (2026-09-20)

Phase C code is on this MacBook branch. Inference still stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions.

Secrets stay in the password manager, not this file.

## Done on the MacBook

- `apps/dashboard` Vite React, no login form, no Netlify Identity, no shared password.
- Netlify site `cloudiator`: https://cloudiator.netlify.app
- `PUBLIC_API_URL` and `ADMIN_SESSION_SECRET` are in the Netlify site env. Copy the secret into the password manager from the Netlify UI (rotate it if a CLI log printed it).
- `npm test` in `apps/dashboard`: build, `grep -r neon.tech dist/` finds nothing.

## You, before the dashboard can mint keys

1. **Netlify site env:** add pooled `DATABASE_URL` (`-pooler` in the host). Server functions only.
2. **Custom domain:** Cloudflare DNS CNAME `app` → `cloudiator.netlify.app`, **proxied**. Then Netlify → Domain management → Add `app.cloudiator.org`. Access is already on that hostname.
3. **Disable the `*.netlify.app` default domain** once `app.cloudiator.org` works. Naked `cloudiator.netlify.app` is not behind Access; an attacker can send `Cf-Access-Authenticated-User-Email` themselves.
4. **Mini:** `git pull` this branch (or `main` after merge) and restart the worker. Phase C adds CORS for `https://app.cloudiator.org` so the playground can call the API from the browser.

## Prove it

- Incognito on `https://app.cloudiator.org` is challenged by **Cloudflare Access**, not a password form.
- Mint a Salesforce-engineer key, copy it once, chat from the playground, refresh usage.
- The Apex snippet on screen contains `setTimeout(120000)` and `"stream": false`.

## Later

| When | What |
| --- | --- |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | Tools, OCR, maps — Mini, Opus 5. |
| Phase F | External Services import of `/tmp/cloudiator-oas.json` (already valid 3.0.3). |
