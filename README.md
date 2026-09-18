# Cloudiator (cldM4)

**This repository is the production plan and later the product.** Right now it contains the implementation bible only. No application code yet.

Remote: `https://github.com/AshrafRezk/cldM4.git`

## What this is

A Mac Mini M4 **24GB** is the AI worker. A small cloud control plane (Netlify dashboard + Cloudflare Tunnel + Neon) mints **scoped OpenAI-compatible API links** for Salesforce orgs and websites. The Mini also runs a **library toolbox** (OCR, maps, charts, stats, DuckDB, image ops, documents) so not every request burns a model.

## If you are on the Mac Mini M4 and ready to build

1. Clone this repo (or `git pull`).
2. Open the folder in Cursor.
3. Read **[PLAN.md](PLAN.md) end to end** before generating code.
4. Execute **one phase at a time** using the copy-paste prompts in **[docs/cursor-phases.md](docs/cursor-phases.md)**.
5. Do not skip Phase A. Do not install Docker for GPU inference. Do not put inference in Netlify Functions.

## If you are not on the Mini

Do **not** run Ollama pulls or LaunchAgents here. You may still read the plan. Implementation that needs Metal, Apple Vision, and 24GB RAM belongs on the Mini.

## Document map

| File | Use |
| --- | --- |
| [PLAN.md](PLAN.md) | Full architecture, models, tools, API, RAM, security, Salesforce, failure modes |
| [docs/cursor-phases.md](docs/cursor-phases.md) | Exact Cursor prompts per phase + definition of done |
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
- One Metal-heavy model at a time on 24GB.
- Libraries first, models last.
