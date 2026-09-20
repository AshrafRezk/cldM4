# Operator checklist — fill this in BEFORE Phase B

Hardware, cables, LAN, and “what is public” live in **[hardware-and-network.md](hardware-and-network.md)**. Do that document first; this file is the account/DNS/boot blanks.

This is the human's job, not the agent's. Every blank below becomes a value in `~/Cloudiator/.env`, a Cloudflare setting, or a Salesforce config field. **Phase B cannot pass its definition of done with blanks in sections 1–5.**

Fill it in, keep this file in the repo with placeholders, and keep the **real** values in a password manager. Do not commit real values — `git diff` this file before every commit.

Legend: `[ ]` not done · `[x]` done · `n/a` deliberately skipped (write why).

---

## 0. Before you touch the Mini (15 min)

- [ ] Uplink chosen (tick exactly one):
  - ☐ **Ethernet** (preferred) — Wi-Fi off after Ethernet is up; DHCP reservation on Ethernet MAC.
  - ☐ **Wi-Fi only** — main SSID (not guest), prefer 5 GHz, DHCP reservation on Wi-Fi MAC, single interface. Phase B must use `protocol: http2` in `~/.cloudflared/config.yml` (see [hardware-and-network.md](hardware-and-network.md) §3).
- [ ] Free disk measured: `df -h /` → **______ GB free**. Need **≥ 120 GB** free for the full v1 model set. Below 80 GB, plan to skip FLUX 8-bit and `gpt-oss:20b`.
- [ ] Mini is not in a closed cabinet.
- [ ] UPS decision: ☐ have one ☐ accepting the risk (see §6, FileVault).
- [ ] Network time is on: System Settings → General → Date & Time → *Set time and date automatically*. Artifact URL signatures expire against this clock.

---

## 1. Domain and DNS

| Item | Value | Done |
| --- | --- | --- |
| Registrar | Cloudflare Registrar | [x] |
| Apex domain | `cloudiator.org` | [x] |
| Nameservers pointed at Cloudflare | Cloudflare dashboard: zone **Active** (`DNS Setup: Full`) | [x] |
| API hostname | `api.cloudiator.org` | [x] |
| Dashboard hostname | `app.cloudiator.org` | [x] |

Do **not** proceed to the tunnel until the Cloudflare zone status is **Active**. A pending zone gives you a working `cloudflared` and a DNS name that resolves nowhere, which looks exactly like a tunnel bug.

---

## 2. Cloudflare

| Item | Value | Done |
| --- | --- | --- |
| Account email | stored in password manager | [x] |
| Zone ID | stored in password manager | [x] |
| Tunnel name | `cloudiator-mini` | [ ] |
| Tunnel UUID | ____________________ | [ ] |
| Credentials file path | `~/.cloudflared/<UUID>.json` | [ ] |
| DNS: `api` CNAME → `<UUID>.cfargotunnel.com`, **proxied** (orange cloud) | Mini, after Phase A | [ ] |

### 2a. Zone settings that must be changed — Salesforce Apex is not a browser

Apex cannot run JavaScript, hold cookies, or solve a challenge. Any Cloudflare feature that answers with an interstitial page turns every Salesforce callout into an HTML body that Apex cannot parse. **This is the single most common way Phase F fails.**

- [x] **Bot Fight Mode: OFF** (Security → Bots). Super Bot Fight Mode: off, or "Allow" for definitely-automated.
- [ ] **Security Level: Essentially Off** for `api.cloudiator.org` (Security → Settings, or a Configuration Rule scoped to the hostname). Skip rule also skips Security Level for `Bearer sk-cld-`.
- [ ] **Browser Integrity Check: OFF** for `api.cloudiator.org`. Skip rule also skips BIC for `Bearer sk-cld-`.
- [x] **No Turnstile / managed challenge** on `api.cloudiator.org`. Ever.
- [x] **"I'm Under Attack" mode is never enabled on this zone** while Salesforce orgs depend on it. If you must enable it during an attack, expect all Apex traffic to fail until you turn it off.

### 2b. WAF Skip rule (create it, then test it)

Security → WAF → Custom rules → **Skip**.

```
(http.host eq "api.cloudiator.org" and starts_with(http.request.headers["authorization"][0], "Bearer sk-cld-"))
```

Skip: **All managed rules**, **Super Bot Fight Mode**, **Rate limiting rules**, **Browser Integrity Check**.

- [x] Rule created and enabled (`skip-sk-cld-salesforce`), placed **above** every other custom rule.
- [ ] Verified: a `curl` with a valid `Authorization: Bearer sk-cld-...` header returns JSON, from a network that is not the Mini. (Needs the Mini tunnel.)

### 2c. Rate limiting

- [x] Cloudflare free plan cannot key rate limiting on the Authorization header (IP only, 10s period only). Left empty on purpose. Per-key `rpm` in the worker is the real enforcement.
- [ ] Limit chosen: n/a (worker `rpm` only until a paid CF plan can do 120/60 on Authorization).

### 2d. Cloudflare Access (dashboard + admin)

- [x] Zero Trust team domain: stored in password manager (`*.cloudflareaccess.com`)
- [x] Access application on `app.cloudiator.org` — policy: allow email `ashrafrmattar@gmail.com`
- [x] Access application on `api.cloudiator.org/v1/admin*` — same allow email
- [x] Application **AUD tag** (needed by the worker to verify the JWT): stored in password manager — use the **api** app AUD as `CF_ACCESS_AUD`
- [ ] Verified: an incognito window on `app.cloudiator.org` is challenged by Access, not by a password form. (Needs Phase C + DNS.)

There is **no shared admin password** in v1. The dashboard has no login screen of its own.

---

## 3. Neon

| Item | Value | Done |
| --- | --- | --- |
| Project name | `cloudiator` | [x] |
| Region (pick nearest the Mini) | AWS Europe West 2 (London) | [x] |
| Database name | `neondb` | [x] |
| **Pooled** connection string (contains `-pooler`) | stored in password manager | [x] |
| Schema from `docs/schema.md` applied | `infra/neon.sql` ran 2026-09-20 | [x] |
| IP allowlist | **off** (none set) | [x] |

- [x] You understand the compute auto-suspends when idle: the first query after a quiet period takes ~0.5–3s. The worker must never block a chat on Neon (60s key cache + usage outbox handle this).
- [ ] Retention job from `docs/schema.md` scheduled or diarised — raw `usage_events` older than 30 days get deleted, otherwise the free tier fills up and **key minting starts failing**.

---

## 4. Netlify

| Item | Value | Done |
| --- | --- | --- |
| Team / site name | ____________________ | [ ] |
| Site URL | ____________________ | [ ] |
| Custom domain `app.<domain>` attached | | [ ] |
| Env `DATABASE_URL` set (server-side only) | | [ ] |
| Env `PUBLIC_API_URL` = `https://api.<domain>` | | [ ] |
| Env `ADMIN_SESSION_SECRET` set | | [ ] |

- [ ] Confirmed `DATABASE_URL` does **not** appear in the built client bundle: `npm run build` then grep `dist/` for `neon.tech`.
- [ ] No Netlify Function calls Ollama or the Mini for inference. Ever.

---

## 5. Nominatim / OpenStreetMap contact details

The OSM Foundation blocks clients with a generic or missing `User-Agent`, and blocks clients exceeding **1 request per second**. A block is applied to your IP, not your key, and it also takes out anything else on your home connection.

| Item | Value | Done |
| --- | --- | --- |
| Contact email that goes in the User-Agent (must be a real, monitored mailbox) | `ashrafrmattar@gmail.com` | [x] |
| `NOMINATIM_USER_AGENT` value | `Cloudiator/0.1 (ashrafrmattar@gmail.com)` | [x] |
| Read the usage policy | https://operations.osmfoundation.org/policies/nominatim/ | [ ] |
| Expected geocode volume per day | dogfood / low until Salesforce orgs are live | [x] |

- [ ] If expected volume exceeds a few thousand a day, or you need bursts above 1 rps, plan to self-host Nominatim or buy a geocoder **before** go-live. The public instance is not a production dependency.
- [ ] Attribution "© OpenStreetMap contributors" is present wherever geocode results are displayed to end users.

---

## 6. Mini physical and boot policy (decide now, it changes the runbook)

FileVault and unattended reboot are in direct conflict. With FileVault on, a cold boot stops at the pre-boot unlock screen: no user session, so **no LaunchAgent runs and Ollama.app does not start**. "Start up automatically after a power failure" only gets you to a locked screen.

Pick exactly one and tick it:

- [ ] **A — FileVault ON + UPS + manual unlock** (recommended). Appliance is encrypted at rest. A power cut longer than the UPS means downtime until a human types the password. Health webhook tells you.
- [ ] **B — FileVault ON, planned reboots only via `sudo fdesetup authrestart`.** This one command unlocks the disk for exactly the next boot. Never use plain `reboot` on this machine. Unplanned power loss still needs a human.
- [ ] **C — FileVault OFF.** Only if the Mini is in a physically controlled location, and you have written that decision down for whoever's CRM data this is. `docs/licenses.md` assumes FileVault is on; if you pick C, record the compensating control here: ____________________

Then, regardless of choice:

- [ ] Automatic login enabled for the appliance account (System Settings → Users & Groups → Automatic login). Without a GUI session, LaunchAgents and Ollama.app do not run.
- [ ] Energy: prevent sleep when display is off, wake for network access, start up after a power failure. Display may sleep; the **computer must not**.
- [ ] Appliance account is a **standard-privileged daily account** with a separate admin account for setup, or a documented reason it is not.
- [ ] Screen lock timeout set, and you know the unlock password is required after every power cut (options A and B).

Who is allowed to log in / SSH to this Mini: ____________________

---

## 7. Alerting

| Item | Value | Done |
| --- | --- | --- |
| `SLACK_WEBHOOK_URL` (or other alert sink) | ____________________ | [ ] |
| Health ping installed (every 2 min) | see `docs/host-setup.md` | [ ] |
| Alert tested by stopping the worker | | [ ] |

An appliance with no alerting is an appliance that is down and nobody knows. If you skip this, you will find out from a Salesforce user.

---

## 8. Model decisions recorded (filled during Phase A step 0)

`PLAN.md` names `gemma4:e4b-it-qat` (Gemma 4 E4B, official QAT **Q4_0**). That tag is the Arabic + vision + tools default. If it does not resolve on build day, Phase A walks the fallback ladder. **Write down what you actually installed** — every later phase, the `DEFAULT_MODEL` env var, and the dashboard presets depend on it.

Do **not** install `gemma4` / `gemma4:latest` (those are the ~9.6 GB Q4_K_M E4B). Do **not** pull `gemma4:26b*` or `gemma4:31b*`. Do **not** use `gemma4:*-mlx` as DEFAULT (Gemma 4 prefix cache). Do **not** install vLLM in Phase A.

| Slot | Planned | Actually installed | Size on disk | Tools? | Vision? | Arabic smoke? |
| --- | --- | --- | --- | --- | --- | --- |
| Default chat | `gemma4:e4b-it-qat` | ______________ | ______ | ☐ | ☐ | ☐ |
| Quality upgrade (optional, **replaces** E4B) | `gemma4:12b-it-qat` | ______________ | ______ | ☐ | ☐ | ☐ |
| Embeddings | `nomic-embed-text` | ______________ | ______ | n/a | n/a | n/a |
| Fallback (optional) | `llama3.2:3b` | ______________ | ______ | ☐ | n/a | n/a |
| Heavy (Phase E, opt-in) | `gpt-oss:20b` | ______________ | ______ | ☐ | ☐ | n/a |

- [ ] `DEFAULT_MODEL` in `.env` matches the "actually installed" default-chat (or 12B upgrade) row. Only one generative chat model is hot.
- [ ] Arabic smoke: a short فصحى prompt returned Arabic, not an English apology.
- [ ] Quant is QAT Q4_0 (`ollama show` / file type), not Q8 or bf16. ☐
- [ ] If the default chat model has **no** vision capability (fallback only), the router is OCR-only for images and the `/v1/chat/completions` vision path returns `model_not_found`. Confirmed and acceptable: ☐
- [ ] `DEFAULT_MODEL_HAS_VISION` in `.env` matches the Vision column above. `scripts/phase-a-gates.sh` prints what `ollama show` reported.

---

## 9. Measured numbers (fill during Phases A and E — do not guess)

The RAM table in `PLAN.md` §4 is an estimate. Replace it with what your machine actually does.

| Measurement | Command | Your value |
| --- | --- | --- |
| Idle free memory, nothing loaded | `vm_stat` / Activity Monitor | ______ GB |
| Resident with Gemma E4B QAT hot (or 12B QAT if that is DEFAULT) | `ollama ps` | ______ GB |
| Gemma tokens/sec warm (English) | Phase A curl timing | ______ tok/s |
| Gemma tokens/sec warm (Arabic) | Phase A curl timing | ______ tok/s |
| Gemma cold load time | Phase A | ______ s |
| TTFT first chat (new prefix) | Phase A curl | ______ s |
| TTFT second chat (same system+tools prefix) | Phase A curl | ______ s — should be lower |
| Peak memory during FLUX 4-bit 1024² | Activity Monitor during Phase E | ______ GB |
| Peak memory during FLUX 8-bit 1024² (only if you enable it) | | ______ GB |
| FLUX 1024² wall clock | Phase E | ______ s |
| Swap used at peak (**must stay 0**) | `sysctl vm.swapusage` | ______ |

If swap is non-zero at any peak, drop to 4-bit FLUX, drop `num_ctx`, or drop `gpt-oss:20b`. Do not "see how it goes".

---

## 10. Salesforce (needed for Phase F, nice to have earlier)

| Item | Value | Done |
| --- | --- | --- |
| Org type | ☐ Developer Edition ☐ Sandbox ☐ Production | [ ] |
| My Domain | ____________________ | [ ] |
| Named Credential name | `Cloudiator` | [ ] |
| External Credential name | ____________________ | [ ] |
| Permission set granting the running user the External Credential **principal** | ____________________ | [ ] |
| Key minted for this org (`public_id` only, never the secret) | ____________________ | [ ] |

The permission-set row is not optional. Without it the callout returns 401 even though the same key works in `curl`, and there is no error message that says so.

---

## 11. Sign-off before Phase B starts

Laptop cloud (2026-09-20): domain, Neon schema, WAF Skip, Access apps. Still open: §0 hardware, §4 Netlify (Phase C), §5 Nominatim policy read, §6 boot policy, tunnel (Mini after Phase A).

- [x] Sections 1–3 public rows filled. Secrets stay in the password manager, not this file.
- [ ] Section 6 has exactly one option ticked. (Mini)
- [ ] `~/Cloudiator/.env` exists, is `chmod 600`, and is **not** inside the git working tree. (Mini)
- [ ] `git status` is clean of secrets; `.env` is ignored.
- [x] You can state, out loud, what happens to Salesforce traffic if you enable Bot Fight Mode. (HTML interstitial; Apex cannot parse it.)

Operator: Ashraf / laptop cloud  Date: 2026-09-20

---

## 12. Next steps (after laptop cloud setup)

Full copy: [next-steps.md](next-steps.md). Secrets stay in the password manager.

1. **This laptop:** `git push` so GitHub has this commit. Do not commit `.env` or connection strings.
2. **Mini — Phase A only** (new Cursor chat, Opus, Auto off). Ethernet, `uname -m` → arm64, FileVault policy in §6, then the Phase A prompt in [cursor-phases.md](cursor-phases.md). Loopback chat must work before any tunnel.
3. **Mini — Phase B remainder:** named tunnel `cloudiator-mini` to `127.0.0.1:8080` only (never 11434), worker key auth, usage outbox. Prove HTTPS from a **phone on cellular**.
4. **Later:** Netlify dashboard (Phase C). Schedule `infra/neon-retention.sql`. Do not create a Cloudflare Worker.
