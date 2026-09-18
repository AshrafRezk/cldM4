# Cursor Pro Plus ($60) settings — build Cloudiator well

This project is **spec-heavy**. The $60 plan is **Cursor Pro Plus**: more usage, not a smarter model. Intelligence comes from **which model you pick** and **one phase per chat**.

Official pools: [Models & Pricing](https://cursor.com/docs/models-and-pricing).

- **Cursor Models pool** (generous): Grok 4.6, Grok 4.5, Composer 2.5
- **Other Models pool** (~$70/mo on Pro Plus): Claude, GPT, Gemini at API rates

Opus is expensive (~$5 input / $25 output per million tokens). Use it where the spec can be violated. Do not use it to write the 12th Pillow helper.

---

## 1. One-time setup on the Mac Mini

1. Install Cursor. Sign in. Confirm **Pro Plus** (Settings → Account / Billing).
2. **File → Open Folder** on the `cldM4` clone (this repo), not a parent directory.
3. Settings → **Agent**: mode **Agent** (not Ask, not a random Cloud Agent for Phase A Metal work).
4. Settings → **Privacy**: turn **Privacy Mode on** (Salesforce/CRM text must not train). Keep it on for the life of this Mini.
5. Settings → **Models**:
   - **Auto: off** for Phases A, B, E (Auto may spend the wrong pool or skip constraints).
   - Pin **Claude Opus 5** (or the newest Opus in the list) as the manual default for architecture.
   - Enable **Claude Sonnet 5** and **Grok 4.6** so you can switch without hunting.
   - If you see **Max Mode** / 1M context (legacy or model toggle): **on** when `@PLAN.md` is in the chat. This plan is long; 8k context will amnesia the RAM rules.
6. Settings → Agent / **Auto-run** (sometimes “YOLO”): **off** or “ask for every terminal command” until Phase A is green. A runaway `ollama pull gpt-oss:120b` will wreck the disk and the 24GB box.
7. Confirm `.cursor/rules/cloudiator.mdc` is listed under project rules (**Always apply**). If Cursor asks to enable project rules, **Allow**.

Do not also pay for a separate Claude.ai subscription unless you want chat outside Cursor. Pro Plus already calls Anthropic.

---

## 2. Every new chat (do this every phase)

1. Click **New Chat**.
2. Set the mode dropdown to **Agent**.
3. Set the **model** from the table below (do not leave Auto).
4. Attach context: type `@PLAN.md` and `@docs/cursor-phases.md`. For later phases also `@docs/host-setup.md` / `@docs/schema.md` / `@docs/salesforce.md` as relevant.
5. Paste the **shared opener** plus **that phase only** from `docs/cursor-phases.md`.
6. Let it run until **definition of done**. Then you review: `curl` health, `ollama ps` (one model), no Docker.
7. Ask it to **commit** that phase. Then **new chat** for the next phase. Never “keep going through D3” in the same thread.

---

## 3. Which model for which phase

| Phase | Pick this in the model menu | Pool | Why |
| --- | --- | --- | --- |
| A Worker, Ollama shim, RAM lock | **Claude Opus 5** | Other | First architecture; easy to get Metal/lock wrong |
| B Neon keys, Cloudflare Tunnel | **Claude Opus 5** | Other | Auth + tunnel mistakes are security bugs |
| C Netlify dashboard | **Claude Sonnet 5** | Other | UI + Neon reads; less RAM-critical |
| D Tool registry, OCR, maps | **Claude Opus 5** | Other | Registry design must match PLAN.md |
| D2 Charts, stats, DuckDB | **Claude Sonnet 5** | Other | Mechanical, high token volume |
| D3 Image ops, docs, mermaid, IDs | **Grok 4.6** or Sonnet | Cursor / Other | Many similar tools; save Opus |
| E mflux FLUX + jobs queue | **Claude Opus 5** | Other | Exclusive RAM slot + Salesforce jobs |
| F Salesforce pack, optional Whisper | **Claude Sonnet 5** | Other | Docs + Apex; Opus if Named Credential auth is messy |
| “Fix this pytest / LaunchAgent” | **Grok 4.6** or **Composer 2.5** | Cursor | Cheap iteration |

If the newest names in your picker are **Opus 4.8 / Sonnet 4.6** instead of 5, use the **latest Opus** for A/B/D/E and the **latest Sonnet** for C/D2/F. Same idea.

**Do not** select local `qwen3.5:9b` as the Cursor model. That is the product you are shipping, not the engineer.

---

## 4. How to spend the $70 Other Models pool

Rough budget for a focused Mini week:

- ~40% Opus on A + B + D + E (few chats, large context, worth it)
- ~40% Sonnet on C + D2 + F
- ~20% leftover for Opus retries when a phase fails DoD

Grok 4.6 for D3 and bugfix loops so you do not wake up to an empty Other Models bar.

If usage warns you are out: switch to **Grok 4.6** immediately. Do not enable unbounded on-demand spend unless you intend to. Settings → Billing → on-demand / spend cap: set a **hard cap** (example $20 extra) so a stuck Agent cannot bill Ultra prices overnight.

Cursor’s own note: daily Agent users often land **$60–$100/mo**. Pro Plus is the right tier; **Ultra ($200)** only if you run many parallel agents.

---

## 5. Chat hygiene (this is what makes it “great”)

- One phase, one PR-sized commit, one green DoD.
- If the agent proposes Docker, 70B, Netlify inference, or loading FLUX beside 9B: stop, point at `PLAN.md`, retry. Do not “let it cook.”
- After every GPU-ish change: `ollama ps` must show **at most one** model.
- After Phase B: test HTTPS from a **phone**, not only localhost.
- Keep the Mini awake (see `docs/host-setup.md`). Cursor Agent cannot fix a sleeping origin.

---

## 6. What you should see in the UI

```
[Agent ▼]  [Claude Opus 5 ▼]     (Phases A, B, D, E)
[Agent ▼]  [Claude Sonnet 5 ▼]   (Phases C, D2, F)
[Agent ▼]  [Grok 4.6 ▼]          (D3, fixes)
```

Context chips: `PLAN.md` `cursor-phases.md`

First user message: the opener in `docs/cursor-phases.md`, then that phase’s fenced prompt. Nothing else.
