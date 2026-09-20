# Cloudiator (cldM4)

**This repository is the production plan and the product.** Phases A and B (the worker, key auth, Neon, and the tunnel) are in `apps/worker`, `packages/schema`, `infra/`, and `scripts/`; the rest of the plan is still plan.

Remote: `https://github.com/AshrafRezk/cldM4.git`

## What this is

A Mac Mini M4 **24GB** is the AI worker. A small cloud control plane (Netlify dashboard + Cloudflare Tunnel + Neon) mints **scoped OpenAI-compatible API links** for Salesforce orgs and websites. The Mini also runs a **library toolbox** (OCR, maps, charts, stats, DuckDB, image ops, documents) so not every request burns a model.

## If you are on the Mac Mini M4 and ready to build

1. Clone this repo (or `git pull`).
2. Do **physical + internet first:** **[docs/hardware-and-network.md](docs/hardware-and-network.md)** (Ethernet, no port forwards, FileVault/UPS, accounts, phone-on-cellular test). Then **[docs/host-setup.md](docs/host-setup.md)** (Homebrew, Ollama.app, LaunchAgents).
3. Open **this folder** in Cursor (Pro Plus / $60).
4. Configure Cursor using **[docs/cursor-settings.md](docs/cursor-settings.md)** (Opus vs Sonnet vs Grok, Privacy Mode, Auto off, no YOLO).
5. Read **[PLAN.md](PLAN.md)** end to end before generating code.
6. Fill in **[docs/operator-checklist.md](docs/operator-checklist.md)** §0 now and §§1–6 before Phase B. Phase B cannot pass with blanks in it.
7. Execute **one phase at a time** with the prompts in **[docs/cursor-phases.md](docs/cursor-phases.md)**. New Agent chat per phase. Attach `@PLAN.md`. Each phase lists the files that must exist, the commands that prove it, and how to roll back.
8. Do not skip Phase A. Do not install Docker for GPU inference. Do not put inference in Netlify Functions.

### Phase A on the Mini, in order

```bash
scripts/phase-a-gates.sh --no-pull      # step 0 + the Phase 0 host checks; changes nothing
cp .env.example ~/Cloudiator/.env && chmod 600 ~/Cloudiator/.env
scripts/mac-setup.sh                    # brew, exclusions, log rotation, venv, Phase A pulls only
scripts/phase-a-gates.sh                # must be green before the worker is trusted
scripts/install-launchagents.sh         # renders the plist, bootstraps, waits for /v1/health
scripts/smoke-phase-a.sh                # the definition of done
```

Roll back with `scripts/install-launchagents.sh --uninstall`, `git checkout -- apps/worker scripts`, and `rm -rf apps/worker/.venv`. Models stay on disk.

### Phase B on the Mini, in order

Needs [docs/operator-checklist.md](docs/operator-checklist.md) §§1–5 filled in, and the pooled `DATABASE_URL`, `CF_ACCESS_AUD`, `CF_ACCESS_TEAM_DOMAIN` in `~/Cloudiator/.env` (`chmod 600`, outside git).

```bash
scripts/apply-neon-schema.sh            # verifies first; applies only what is missing
cd apps/worker && .venv/bin/python -m app.dbtool mint-key \
  --tenant cloudiator --name 'Phase B smoke' --preset salesforce_engineer   # shown once
cd - && cloudflared tunnel login        # human, browser, zone must be Active
scripts/install-tunnel.sh               # named tunnel -> 127.0.0.1:8080 only
export SMOKE_API_KEY=sk-cld-...
scripts/smoke-phase-b.sh                # the definition of done
```

Then do the three things a script cannot: repeat the HTTPS checks from a **phone on cellular**, import `?target=salesforce` OpenAPI into External Services in a dev org, and run the Neon-down drill.

Roll back with `scripts/install-tunnel.sh --uninstall` (and `cloudflared tunnel delete cloudiator-mini` plus the DNS record if you want the tunnel gone), `.venv/bin/python -m app.dbtool revoke-key <public_id>` for any key you minted, and `git checkout -- apps/worker scripts`. The Phase A loopback worker keeps working untouched.

## If you are not on the Mini

Do **not** run Ollama pulls or LaunchAgents here. You may still read the plan. Implementation that needs Metal, Apple Vision, and 24GB RAM belongs on the Mini.

## Document map

| File | Use |
| --- | --- |
| [PLAN.md](PLAN.md) | Full architecture, models, tools, API, RAM, security, Salesforce, failure modes |
| [docs/hardware-and-network.md](docs/hardware-and-network.md) | **Day 0.** Physical Mini, Ethernet, CGNAT, no port forwards, accounts, prove-internet commands |
| [docs/operator-checklist.md](docs/operator-checklist.md) | **Fill this in before Phase B.** Domain, Cloudflare zone settings, Neon, Netlify, Nominatim contact, boot policy |
| [docs/next-steps.md](docs/next-steps.md) | **After laptop cloud setup.** Phase A on the Mini, then tunnel. Do not put secrets here |
| [docs/plan-review-findings.md](docs/plan-review-findings.md) | Pre-Phase-A audit: P0/P1/P2 findings and where each fix landed |
| [docs/cursor-settings.md](docs/cursor-settings.md) | Cursor Pro Plus ($60): model picker, Privacy Mode, spend cap, per-phase model |
| [docs/plan-review-prompt.md](docs/plan-review-prompt.md) | Opus 5 prompt to re-audit the plan (already run once; keep for later) |
| [docs/cursor-phases.md](docs/cursor-phases.md) | Exact Cursor prompts per phase + files, proof commands, and rollback |
| [docs/env.md](docs/env.md) | Every environment variable |
| [docs/schema.md](docs/schema.md) | Neon / Postgres DDL |
| [docs/host-setup.md](docs/host-setup.md) | macOS, Homebrew, Ollama, LaunchAgents, tunnel |
| [docs/salesforce.md](docs/salesforce.md) | Named Credentials, Apex, External Services, 120s limit, 15/18 Ids |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Known failures and fixes |
| [docs/licenses.md](docs/licenses.md) | Model and library licenses |
| [.env.example](.env.example) | Mini worker env template (copy, do not commit secrets) |
| [apps/worker/](apps/worker/) | Phases A–B: FastAPI worker, RAM scheduler, key auth, usage outbox, tests |
| [packages/schema/](packages/schema/) | OpenAPI fragments, scope enums, the per-key document generator |
| [scripts/](scripts/) | Gates, host setup, LaunchAgents, Neon schema, tunnel, phase smokes |
| [infra/launchd/](infra/launchd/) | LaunchAgent templates (worker and cloudflared) |
| [infra/cloudflared/](infra/cloudflared/) | Tunnel config template: one origin, `127.0.0.1:8080` |

## Locked v1 decisions

- OpenAI-compatible API **plus** Cloudiator extras (usage, jobs, per-key OpenAPI, tools).
- **No video generation** in v1.
- Inference **never** runs on Netlify (timeouts).
- One Metal-heavy model at a time on 24GB, enforced by the worker's scheduler and `uvicorn --workers 1`.
- Default chat is **Gemma 4 E4B QAT GGUF** (`gemma4:e4b-it-qat`, 4-bit) for Arabic + English + image understanding. Image *generation* is still FLUX 4-bit, exclusive.
- Inference in v1 is **Ollama GGUF, one in-flight generation**. vLLM-metal (paged KV / continuous batching) is a v1.1 exclusive experiment, not a Phase A install.
- Libraries first, models last.
- The FastAPI worker is the only thing that validates API keys. Cloudflare does TLS, DDoS, and a WAF skip rule — Salesforce Apex cannot answer a bot challenge.
- Admin and dashboard sit behind Cloudflare Access. No shared password anywhere.
