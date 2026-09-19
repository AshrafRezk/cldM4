# Cloudiator (cldM4)

**This repository is the production plan and the product.** Phase A worker code lives in `apps/worker`. Mini hardware proofs are still required. Status board: **[docs/progress.md](docs/progress.md)**.

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
7. Pull this repo. **Phase A application code is already in `apps/worker`.** On the Mini run `scripts/mac-setup.sh`, then the Phase A **Prove it** commands in **[docs/cursor-phases.md](docs/cursor-phases.md)**. Track done / not done / manual in **[docs/progress.md](docs/progress.md)**. New Agent chat for Phase B only after those proofs are green.
8. Do not skip Mini proofs. Do not install Docker for GPU inference. Do not put inference in Netlify Functions.

## If you are not on the Mini

You may run `cd apps/worker && uv sync --extra dev && uv run pytest -q` (set `CLOUDIATOR_ENV=test`). Do **not** run Ollama pulls or LaunchAgents here. Metal, Apple Vision, and 24GB RAM proofs belong on the Mini. See [docs/progress.md](docs/progress.md) for what is code-complete vs what only you can tick.

## Document map

| File | Use |
| --- | --- |
| [docs/progress.md](docs/progress.md) | **What is done / not done / manual.** Start here if you are asking “where are we?” |
| [PLAN.md](PLAN.md) | Full architecture, models, tools, API, RAM, security, Salesforce, failure modes |
| [docs/hardware-and-network.md](docs/hardware-and-network.md) | **Day 0.** Physical Mini, Ethernet, CGNAT, no port forwards, accounts, prove-internet commands |
| [docs/operator-checklist.md](docs/operator-checklist.md) | **Fill this in before Phase B.** Domain, Cloudflare zone settings, Neon, Netlify, Nominatim contact, boot policy |
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

## Locked v1 decisions

- OpenAI-compatible API **plus** Cloudiator extras (usage, jobs, per-key OpenAPI, tools).
- **No video generation** in v1.
- Inference **never** runs on Netlify (timeouts).
- One Metal-heavy model at a time on 24GB, enforced by the worker's scheduler and `uvicorn --workers 1`.
- Libraries first, models last.
- The FastAPI worker is the only thing that validates API keys. Cloudflare does TLS, DDoS, and a WAF skip rule — Salesforce Apex cannot answer a bot challenge.
- Admin and dashboard sit behind Cloudflare Access. No shared password anywhere.
