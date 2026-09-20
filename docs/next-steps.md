# Next steps — stop recorded 2026-09-20 ~22:09 UTC

Inference stays on the Mini. **Do not create a Cloudflare Worker.** Do not put inference in Netlify Functions. Do not put secrets in this file.

**Last thing actually done:** dashboard playground chat from `https://app.cloudiator.org` → `https://api.cloudiator.org` returned Arabic (Salesforce sentence). Mini OPTIONS preflight is **204** with `access-control-allow-origin: https://app.cloudiator.org`. The operator then **revoked many keys** and stopped. The leftover Phase C checks below were **not** done.

Do not start Phase D until those leftover checks are green, or until the operator explicitly skips them.

## Where the code is

- Branch: `cursor/cloud-agent-1789940810344-piopm` (PR https://github.com/AshrafRezk/cldM4/pull/9). There is **no** `cursor/phase-c-netlify-dashboard` on GitHub.
- Mini (`~/cldM4`) is on that branch, worker restarted after checkout. **Not** back on `main`.
- Dashboard is live on Netlify Drop at `https://app.cloudiator.org` (site `cloudiator`). Last deploy from Netlify Drop / CLI `--no-build`; the Netlify UI has **no Trigger deploy** until the site is Git-linked.

## Proven

- Cloudflare Access is on `app.cloudiator.org` (operator logged in as `ashrafrmattar@gmail.com`). Not re-checked in incognito.
- Pooled Neon `DATABASE_URL` is in Netlify site env (server-side). Dashboard mint/list/revoke works.
- Tenant `cloudiator` visible in the UI.
- CORS on the Mini worker: `OPTIONS /v1/chat/completions` from origin `https://app.cloudiator.org` → 204.
- One playground chat succeeded (Arabic, Salesforce prompt) with a Salesforce-engineer key, then that key and several others were revoked.

## Keys (2026-09-20)

All of these dashboard rows showed **revoked** after the playground proof. `public_id` only (never store the secret here):

| Name | public_id | Notes |
| --- | --- | --- |
| Salesforce org | `3id2agzqwmg7` | Playground success, then revoked (also appeared in a screenshot) |
| Salesforce org | `fcq3567r7dih` | revoked |
| Salesforce org | `rzo7uuany4qu` | revoked |
| Salesforce org | `qdej5o4oerhw` | revoked |
| Salesforce org | `nhdbs2bmbcdh` | revoked (earlier screenshot leak) |
| Phase B smoke | `97ktd26abuzf` | revoked |
| Phase B smoke | `o4ig8h9ncxhn` | revoked |
| Phase B smoke | `fk5r7c2naido` | revoked |

Worker key cache can take **up to 60s** to honour revoke. Mint a **new** key before the next playground or `curl` test. Do not paste full `sk-cld-…` secrets into chat or screenshots.

## Not done (Phase C leftover)

The operator did **not** do these after the playground reply:

- [ ] Refresh the **usage** chart and confirm a `usage_daily` row for the playground chat.
- [ ] Download **both** OpenAPI files (normal + Salesforce External Services).
- [ ] Confirm the on-screen Apex snippet contains `setTimeout(120000)` and `"stream": false`.
- [ ] Incognito window on `https://app.cloudiator.org` challenged by **Cloudflare Access**, not a password form.
- [ ] Disable Netlify’s `*.netlify.app` default domain (`cloudiator.netlify.app` is not behind Access).
- [ ] Merge PR #9 and `git checkout main && git pull` on the Mini.
- [ ] Rotate `ADMIN_SESSION_SECRET` if a CLI log printed it; copy the current value into the password manager.

## When you pick this up

1. Mint a new Salesforce-engineer key (old ones above are dead). Copy it once.
2. Finish the leftover checks, or skip them in writing and start Phase D anyway.
3. Merge PR #9 when ready so the Mini is not stuck on the cloud-agent branch.

## Later (not now)

| When | What |
| --- | --- |
| This week | Schedule `infra/neon-retention.sql` (free-tier storage). |
| Phase D | **New chat on the Mini**, Opus 5, Auto off. Attach `@PLAN.md` `@docs/cursor-phases.md`. Paste the Phase D block only (tools, OCR, maps). |
| Phase F | External Services import of Salesforce OAS. |
