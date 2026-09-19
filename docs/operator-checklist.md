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
| Registrar | ____________________ | [ ] |
| Apex domain | `____________________` | [ ] |
| Nameservers pointed at Cloudflare | (Cloudflare dashboard shows zone **Active**) | [ ] |
| API hostname | `api.____________________` | [ ] |
| Dashboard hostname | `app.____________________` | [ ] |

Do **not** proceed to the tunnel until the Cloudflare zone status is **Active**. A pending zone gives you a working `cloudflared` and a DNS name that resolves nowhere, which looks exactly like a tunnel bug.

---

## 2. Cloudflare

| Item | Value | Done |
| --- | --- | --- |
| Account email | ____________________ | [ ] |
| Zone ID | ____________________ | [ ] |
| Tunnel name | `cloudiator-mini` | [ ] |
| Tunnel UUID | ____________________ | [ ] |
| Credentials file path | `~/.cloudflared/<UUID>.json` | [ ] |
| DNS: `api` CNAME → `<UUID>.cfargotunnel.com`, **proxied** (orange cloud) | | [ ] |

### 2a. Zone settings that must be changed — Salesforce Apex is not a browser

Apex cannot run JavaScript, hold cookies, or solve a challenge. Any Cloudflare feature that answers with an interstitial page turns every Salesforce callout into an HTML body that Apex cannot parse. **This is the single most common way Phase F fails.**

- [ ] **Bot Fight Mode: OFF** (Security → Bots). Super Bot Fight Mode: off, or "Allow" for definitely-automated.
- [ ] **Security Level: Essentially Off** for `api.<domain>` (Security → Settings, or a Configuration Rule scoped to the hostname).
- [ ] **Browser Integrity Check: OFF** for `api.<domain>`.
- [ ] **No Turnstile / managed challenge** on `api.<domain>`. Ever.
- [ ] **"I'm Under Attack" mode is never enabled on this zone** while Salesforce orgs depend on it. If you must enable it during an attack, expect all Apex traffic to fail until you turn it off.

### 2b. WAF Skip rule (create it, then test it)

Security → WAF → Custom rules → **Skip**.

```
(http.host eq "api.<domain>" and starts_with(http.request.headers["authorization"][0], "Bearer sk-cld-"))
```

Skip: **All managed rules**, **Super Bot Fight Mode**, **Rate limiting rules**, **Browser Integrity Check**.

- [ ] Rule created and enabled, placed **above** every other custom rule.
- [ ] Verified: a `curl` with a valid `Authorization: Bearer sk-cld-...` header returns JSON, from a network that is not the Mini.

### 2c. Rate limiting

- [ ] Rate limiting rule on `api.<domain>` keyed on the **Authorization header**, not IP. Salesforce egress IPs are shared across many orgs — an IP-keyed limit lets one tenant throttle another.
- [ ] Limit chosen: ______ requests / ______ seconds. Start generous (e.g. 120/60) and tighten. Per-key `rpm` in the worker is the real enforcement; this rule is only DDoS insurance.

### 2d. Cloudflare Access (dashboard + admin)

- [ ] Zero Trust team domain: `____________________.cloudflareaccess.com`
- [ ] Access application on `app.<domain>` — policy: allow email `____________________` (and any other operator).
- [ ] Access application on `api.<domain>/v1/admin*` — same policy.
- [ ] Application **AUD tag** (needed by the worker to verify the JWT): `____________________`
- [ ] Verified: an incognito window on `app.<domain>` is challenged by Access, not by a password form.

There is **no shared admin password** in v1. The dashboard has no login screen of its own.

---

## 3. Neon

| Item | Value | Done |
| --- | --- | --- |
| Project name | ____________________ | [ ] |
| Region (pick nearest the Mini) | ____________________ | [ ] |
| Database name | `neondb` | [ ] |
| **Pooled** connection string (contains `-pooler`) | stored in password manager | [ ] |
| Schema from `docs/schema.md` applied | | [ ] |
| IP allowlist | **off** (home ISP IP rotates) — or document your static egress plan | [ ] |

- [ ] You understand the compute auto-suspends when idle: the first query after a quiet period takes ~0.5–3s. The worker must never block a chat on Neon (60s key cache + usage outbox handle this).
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
| Contact email that goes in the User-Agent (must be a real, monitored mailbox) | ____________________ | [ ] |
| `NOMINATIM_USER_AGENT` value | `Cloudiator/0.1 (____________________)` | [ ] |
| Read the usage policy | https://operations.osmfoundation.org/policies/nominatim/ | [ ] |
| Expected geocode volume per day | ______ | [ ] |

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

`PLAN.md` names `qwen3.5:9b`. If that tag does not resolve on build day, Phase A walks the fallback ladder. **Write down what you actually installed** — every later phase, the `DEFAULT_MODEL` env var, and the dashboard presets depend on it.

| Slot | Planned | Actually installed | Size on disk | Tools? | Vision? |
| --- | --- | --- | --- | --- | --- |
| Default chat | `qwen3.5:9b` | ______________ | ______ | ☐ | ☐ |
| Embeddings | `nomic-embed-text` | ______________ | ______ | n/a | n/a |
| Fallback (optional) | `llama3.2:3b` | ______________ | ______ | ☐ | n/a |
| Heavy (Phase E, opt-in) | `gpt-oss:20b` | ______________ | ______ | ☐ | ☐ |
| Vision (only if needed) | — | ______________ | ______ | n/a | ☐ |

- [ ] `DEFAULT_MODEL` in `.env` matches the "actually installed" row.
- [ ] If the default chat model has **no** vision capability, the router is OCR-only for images and the `/v1/chat/completions` vision path returns `model_not_found`. Confirmed and acceptable: ☐
- [ ] `DEFAULT_MODEL_HAS_VISION` in `.env` matches the Vision column above. `scripts/phase-a-gates.sh` prints what `ollama show` reported.

---

## 9. Measured numbers (fill during Phases A and E — do not guess)

The RAM table in `PLAN.md` §4 is an estimate. Replace it with what your machine actually does.

| Measurement | Command | Your value |
| --- | --- | --- |
| Idle free memory, nothing loaded | `vm_stat` / Activity Monitor | ______ GB |
| Resident with 9B hot | `ollama ps` | ______ GB |
| 9B tokens/sec warm | Phase A curl timing | ______ tok/s |
| 9B cold load time | Phase A | ______ s |
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

- [ ] Sections 1–5 have no blanks.
- [ ] Section 6 has exactly one option ticked.
- [ ] `~/Cloudiator/.env` exists, is `chmod 600`, and is **not** inside the git working tree.
- [ ] `git status` is clean of secrets; `.env` is ignored.
- [ ] You can state, out loud, what happens to Salesforce traffic if you enable Bot Fight Mode.

Operator: ____________________  Date: ____________
