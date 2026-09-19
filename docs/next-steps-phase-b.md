# Next steps — Phase B operator work (other laptop)

**Phase A is done** on the Mac Mini: local chat + embeddings on `127.0.0.1:8080`, swap 0.

**You cannot start Phase B coding until this file’s steps 1–6 are done.** This work is accounts and DNS. Do it on a **normal laptop/browser**, not on the Mini.

The Mini stays on. Do not quit Ollama. Do not Force Quit the worker.

Blanks to copy into later: [operator-checklist.md](operator-checklist.md) §§1–3 and §5. Do **not** commit real secrets.

---

## Fetch this file on the other laptop

```bash
cd ~/cldM4   # or wherever you clone
git fetch origin
git checkout cursor/phase-a-openai-shim-ee9d
git pull origin cursor/phase-a-openai-shim-ee9d
```

Open: `docs/next-steps-phase-b.md`

If you do not have the repo yet:

```bash
git clone https://github.com/AshrafRezk/cldM4.git
cd cldM4
git checkout cursor/phase-a-openai-shim-ee9d
```

---

## Do not do these

- **Do not create or buy the domain on Netlify.** Netlify is Phase C (dashboard website only). The API hostname must live on **Cloudflare DNS**.
- Do not open router ports 22, 8080, 11434, or 443 to the WAN.
- Do not Connect ChatGPT / Claude inside the Ollama Apps window.
- Do not `ollama pull` 20B / 70B / 120B.
- Do not paste the Neon password or `DATABASE_URL` into git, Slack, or an Agent chat.
- Do not use a Cloudflare **quick tunnel** (`cloudflared tunnel --url ...`). Named tunnel only, later, **on the Mini**.

---

## Step 1 — Choose a domain name

Write one apex domain, for example `example.com`.

You will use:

| Hostname | Purpose | When |
| --- | --- | --- |
| `example.com` | Apex (root) | Now (DNS only) |
| `api.example.com` | Public API (tunnel to the Mini) | Phase B |
| `app.example.com` | Dashboard | Phase C (Netlify later) |

**Done when:** you know the exact string, including `.com` / `.net` / etc.

---

## Step 2 — Buy the domain (not Netlify)

Pick **one**:

### Option A — Easiest: buy at Cloudflare Registrar

1. Go to [https://dash.cloudflare.com](https://dash.cloudflare.com) and create/sign in.
2. **Domain registration** → search → buy the name.
3. DNS is already on Cloudflare. Skip Step 3 nameserver copy. Go to Step 4 and wait until the zone is **Active**.

### Option B — You already own it (Namecheap, Google, GoDaddy, …)

1. Sign in at that registrar. Do **not** move it to Netlify.
2. Continue to Step 3.

### Option C — Buy at Namecheap / Google / etc. (new)

1. Buy the domain at that registrar.
2. Continue to Step 3 (you must point nameservers at Cloudflare).

**Done when:** you paid (or already own it) and can open the registrar’s DNS / nameserver screen.

---

## Step 3 — Put the domain on Cloudflare (required if you did not use Option A)

1. [https://dash.cloudflare.com](https://dash.cloudflare.com) → **Add a site** (or **Add** → enter `example.com`).
2. Free plan is enough for v1.
3. Cloudflare shows **two nameservers**, like:

   `xxx.ns.cloudflare.com`  
   `yyy.ns.cloudflare.com`

4. At the **registrar** (not Netlify, not Neon):

   - Find **Nameservers** / **Change nameservers** / **Custom DNS**.
   - Replace the registrar’s default nameservers with those **two** Cloudflare nameservers.
   - Save.

5. Back in Cloudflare, the zone will say **Pending** until the internet picks up the change.

**Done when:** you saved the two Cloudflare nameservers at the registrar.

---

## Step 4 — Wait until Cloudflare says Active

1. Cloudflare dashboard → your domain → overview.
2. Status must be **Active**.
3. If it still says **Pending**, wait. This can be 5 minutes or up to 24–48 hours. Refresh later. Do **not** build the tunnel while Pending.

**Done when:** the badge is **Active**. Write “Active” in [operator-checklist.md](operator-checklist.md) §1 (placeholders only in git; real domain can stay in your notes).

Also write (in your notes, not git if you consider the domain private — the plan expects the domain in the checklist as a hostname, not a secret):

- Registrar: ________
- Apex: `________`
- API host: `api.________`
- Dashboard host: `app.________`

---

## Step 5 — Turn off bot walls (Salesforce is not a browser)

Still in Cloudflare, on this zone:

1. **Security → Bots**
   - **Bot Fight Mode: Off**
   - Super Bot Fight Mode: off, or “Allow” for definitely-automated traffic
2. **Security → Settings**
   - Do **not** enable **I’m Under Attack**
3. Do **not** add Turnstile / managed challenge on `api.` (you will create `api.` in Phase B)

You can leave the rest of the zone on a normal security level for the marketing site; Phase B will scope “essentially off” to `api.` with a Configuration Rule.

**Done when:** Bot Fight is off and Under Attack is not on.

---

## Step 6 — Create Neon (keys and usage — not the model)

The Mini still runs the model. Neon only stores API keys and usage.

1. Go to [https://console.neon.tech](https://console.neon.tech) and sign in.
2. **New project**. Name e.g. `cloudiator`. Region: something reasonably close to you (or to the Mini).
3. Open the project → **Dashboard** / **Connection details**.
4. You will see more than one URI. You want the **pooled** one:
   - The **host** must contain **`-pooler`**
   - Example shape (fake):  
     `postgresql://user:secret@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
5. Copy it into a **password manager**. Not Notes on the desktop. Not this repo.
6. Leave **IP allowlist off** (home Wi-Fi IP rotates).

Do **not** apply `docs/schema.md` from the laptop unless you are comfortable with `psql`. Phase B on the Mini will apply schema. Saving the pooled URL is enough for this week.

**Done when:** pooled URI is in the password manager and you have **not** committed it.

---

## Step 7 — Pick a real email (Nominatim / maps, later)

Use a mailbox you actually read.

You will later set:

`NOMINATIM_USER_AGENT=Cloudiator/0.1 (you@that-email)`

A fake or empty User-Agent can get your **home IP** blocked by OpenStreetMap, which takes out the whole house connection.

**Done when:** you know the email address.

---

## Step 8 — Skip Netlify

Do **not**:

- Buy a domain at Netlify
- Add a Netlify site yet
- Point nameservers at Netlify

Phase C will: create a Netlify site, attach **custom domain** `app.yourdomain`, keep DNS in Cloudflare (CNAME, orange cloud).

---

## Step 9 — What you do **not** do on the other laptop

| Task | Where | When |
| --- | --- | --- |
| `cloudflared tunnel login` / `tunnel create` | **Mini only** | Phase B Agent chat |
| Edit `~/Cloudiator/.env` with `DATABASE_URL` | **Mini only** | Phase B |
| LaunchAgent for cloudflared | **Mini only** | Phase B |
| Cursor Phase B prompt | New Agent chat, after this list | After you reply “Active + Neon saved” |

---

## Step 10 — Reply when 1–7 are true

Send in chat (no passwords, no connection strings):

```
Domain: _______________
Registrar: _______________
Cloudflare zone: Active
Bot Fight: off
Neon: pooled URL saved in password manager (not pasted)
Contact email: _______________
```

Then: **new Agent chat**, model Opus, attach `PLAN.md` and `docs/cursor-phases.md`, paste **Phase B only** from `docs/cursor-phases.md`.

---

## After that (Phase B, on the Mini — not today)

Someone will, on the Mini:

1. `cloudflared tunnel login` then `cloudflared tunnel create cloudiator-mini`
2. DNS `api.<domain>` CNAME to `<uuid>.cfargotunnel.com`, **proxied** (orange cloud)
3. Tunnel ingress: **only** `http://127.0.0.1:8080` — **never** port 11434
4. WAF Skip rule for `Bearer sk-cld-`
5. Cloudflare Access on `app.` and `api./v1/admin*`
6. Worker: API keys, Neon client, usage outbox
7. Prove from a **phone on cellular**, not Mini Wi-Fi

Rollback if it goes wrong: delete the tunnel; Phase A loopback (`127.0.0.1:8080`) stays up.

---

## Short memory aid

1. Domain — **not Netlify**  
2. Cloudflare nameservers → wait **Active**  
3. Bot Fight **off**  
4. Neon **pooled** URL in password manager  
5. Real email  
6. Come back — then Mini tunnel + keys  
