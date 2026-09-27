# Where we are — corrected 2026-09-27

The earlier note on this branch was written from `main` and was wrong about the dashboard. `main` does not contain Phase C. The live site does.

**Do not rebuild the dashboard.**

## Retrieved

`git fetch origin` on 2026-09-27. `origin/main` is still `6c2c1f0` (Phase B, PR #8). The dashboard is:

- Branch `cursor/cloud-agent-1789940810344-piopm`
- PR https://github.com/AshrafRezk/cldM4/pull/9 (open, mergeable, not on `main`)
- Mini checkout is that branch, not `main`
- `https://app.cloudiator.org` is live (Cloudflare Access; a fetch without a session returns 403, not a password form)

Last commit on that branch: `688968e` “Record Phase C stop: playground proven, leftover checks open” (2026-09-20 22:10 UTC).

## Proven there

- Dashboard mint, list, and revoke against Neon. Tenant `cloudiator` is in the UI.
- Playground chat from `https://app.cloudiator.org` to `https://api.cloudiator.org` returned Arabic. Worker OPTIONS preflight is 204 with `access-control-allow-origin: https://app.cloudiator.org`.
- Netlify site `cloudiator`: pooled `DATABASE_URL`, `PUBLIC_API_URL`, `ADMIN_SESSION_SECRET`. No inference in functions.
- The keys used that night were revoked. `public_id`s are listed on that branch’s `docs/next-steps.md`. Mint a new key before the next test. Revoke takes up to 60 seconds.

## Still open (do these before Phase D)

The operator stopped after the playground reply. These were not done:

- [ ] Refresh the usage chart and confirm a `usage_daily` row for a playground chat. The chart reads `usage_daily`, and the nightly rollup is still not scheduled, so a chat from today may not appear until `infra/neon-retention.sql` has run.
- [ ] Download both OpenAPI files (plain and `?target=salesforce`). The buttons are in the dashboard.
- [ ] Confirm the on-screen Apex snippet contains `setTimeout(120000)` and `"stream": false`. The source in `apps/dashboard/src/salesforceSnippets.js` on PR #9 already does.
- [ ] Incognito on `https://app.cloudiator.org` is challenged by Cloudflare Access, not a password form.
- [ ] Disable `cloudiator.netlify.app`. It is not behind Access, so the email header can be spoofed there.
- [ ] Merge PR #9, then `git checkout main && git pull` on the Mini.
- [ ] Copy `ADMIN_SESSION_SECRET` into the password manager if a CLI log printed it.

## After that

| When | What |
| --- | --- |
| Before a client depends on the Mini | Boot policy (checklist §6), health alert (§7), schedule `infra/neon-retention.sql`, fill measured RAM and tok/s (§8–§9). |
| Phase D | New chat on the Mini. Opus 5. Auto off. Tools, OCR, maps. Paste only the Phase D block. |
| Speech | No speak model. No listen endpoint. Whisper large-v3-turbo is the planned listener (Phase F, not pulled). Gemma writes text. Kokoro-82M would speak English and seven other languages and does not speak Arabic; it is not in v1. |

Inference stays on the Mini. Do not create a Cloudflare Worker. Do not put secrets in this file.
