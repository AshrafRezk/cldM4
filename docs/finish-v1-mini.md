# Finish v1 on the Mac Mini

Use this when you continue the Cloud Agent / Cursor chat **on the Mini**. Goal: close the last two finish-line items, then stop.

Proven already (do not redo):

| Item | Proof |
| --- | --- |
| 1. Swap clear / health ok | Post-reboot `post-reboot-finish-line.sh` / `/v1/health` |
| 2. Playground + `usage_daily` | Console chat + Usage tab |
| 3. Neon retention nightly | LaunchAgent + `run-neon-retention.sh` |
| 4. Netlify hostname → Access | `curl -sI https://cloudiator.netlify.app/` → **301** `https://app.cloudiator.org/` (deployed 2026-10-12) |

Still open:

| # | Item | Where |
| --- | --- | --- |
| 5 | Real Salesforce Apex callout + External Services | SF org + Mini tunnel up |
| 6 | FileVault policy + auto-login/energy + Slack health alert | Mini + checklist §6–7 |

Phase G (SIM phone, [#21](https://github.com/AshrafRezk/cldM4/pull/21)) is **after** v1 — do not block finish on it.

---

## Session 0 — every Mini chat (paste first)

```
You are implementing Cloudiator from this repo on the Mac Mini.
Read PLAN.md, docs/cursor-settings.md, docs/finish-v1-mini.md, docs/next-steps.md.
Do not skip RAM rules. No Docker for Ollama. No Netlify inference.
Work only on the finish-line item I name next. Prefer libraries and org config over new models.
Do not pull gpt-oss:20b, gemma4:26b, gemma4:31b. Do not commit secrets.
```

Then pull before anything else:

```bash
cd /Users/ashrafrezk/cldM4
git checkout main
git pull origin main
```

---

## Session A — Salesforce (finish-line 5)

**Model:** Claude Sonnet 5 (or Opus). Attach `@docs/finish-v1-mini.md` `@docs/salesforce.md` `@docs/operator-checklist.md`.

```
Finish-line 5 only — Salesforce pack proof.

1. Confirm Mini worker is up: curl -s http://127.0.0.1:8080/v1/health | python3 -m json.tool
   Expect ok true, swap_used_mb 0.
2. Cloudflare JSON smoke (must be JSON, not HTML):
   curl -s -A 'Salesforce/1.0' -o /tmp/r.txt -w '%{http_code}\n' https://api.cloudiator.org/v1/health
   head -c 200 /tmp/r.txt
   If HTML: fix operator-checklist §2a (Security Level Essentially Off + BIC OFF for api.cloudiator.org) before Apex.
3. I will mint a Salesforce engineer key in https://app.cloudiator.org/console — I paste only public_id into checklist §10, never the secret into git.
4. Walk me through Named Credential + External Credential + Principal + permission set from docs/salesforce.md (step 5 permission set is mandatory).
5. Help me download GET /v1/openapi.json?target=salesforce with that key and import External Services (OpenAPI 3.0.3).
6. Deploy examples/salesforce/CloudiatorChatCallout.cls (or Anonymous Apex from docs/salesforce.md) with setTimeout(120000), stream false. Prove chat JSON < 120s. Log X-Request-Id.
7. Prove ONE job poll pattern (A Queueable in examples/salesforce/CloudiatorJobPoller.cls, or B/C). One poll per transaction.
8. Tick operator-checklist §10 rows that we complete. Do not invent org credentials.
Stop when Apex chat returns JSON and one poll pattern is proven.
```

Apex sources in-repo: [examples/salesforce/](../examples/salesforce/).

---

## Session B — Boot policy + Slack alert (finish-line 6)

**Model:** Claude Sonnet 5. Attach `@docs/finish-v1-mini.md` `@docs/operator-checklist.md` `@docs/host-setup.md`.

```
Finish-line 6 only — unattended boot + alerting.

1. I will tick exactly one of operator-checklist §6 A / B / C (recommend A: FileVault ON + UPS + manual unlock). Do not change FileVault yourself; confirm my choice is recorded.
2. Guide Automatic login for ashrafrezk + Energy (computer never sleeps; wake for network; start up after power failure).
3. Add SLACK_WEBHOOK_URL to /Users/ashrafrezk/Cloudiator/.env (chmod 600). Never commit it.
4. Run scripts/install-health-alert-launchagent.sh and prove launchctl print gui/$UID/ai.cloudiator.health-alert.
5. Stop the worker once, wait for Slack alert, start worker again. Tick checklist §7.
6. Optional same sitting: Nominatim policy tick §5; fill §0 free disk and §8 model rows if still blank.
Stop when the alert has fired once in a real stop/start drill.
```

---

## Session C — optional after v1 green

```
Phase G only when I say so. PR https://github.com/AshrafRezk/cldM4/pull/21
Do not block v1. No CPaaS. SIM via Android bridge. Whisper/TTS exclusive slot rules from PLAN.md.
```

Or backlog ideas: [future-phases.md](future-phases.md).

---

## Definition of done (v1)

```bash
# Netlify (anywhere)
curl -sI https://cloudiator.netlify.app/ | grep -iE 'HTTP/|location:'
# → 301 + location: https://app.cloudiator.org/

# Mini health
curl -s http://127.0.0.1:8080/v1/health | python3 -c 'import sys,json; h=json.load(sys.stdin); assert h.get("ok") and h.get("swap_used_mb",1)==0'

# Salesforce: Apex chat JSON + one poll pattern (org debug log)
# Boot: checklist §6 one of A/B/C ticked; §7 alert tested
```

Then update [next-steps.md](next-steps.md) finish-line boxes 5–6 to `[x]` and checklist §10/§6/§7.
