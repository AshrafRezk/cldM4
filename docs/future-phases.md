# Future phases — ideas that fit this Mac Mini M4 24GB

Not a commitment to build order. These are the next “make Cloudiator amazing” bets that respect the appliance rules: **one Metal generative slot**, no Docker inference, no Netlify models, no 70B/120B.

v1 finish line (ops + Phase F) lives in [next-steps.md](next-steps.md). Phase G (SIM phone agent) is separate. This file is **what comes after** those are green.

---

## Already shipped (do not rebuild)

| Capability | Phase |
| --- | --- |
| Chat + Arabic/EN + vision (Gemma E4B QAT) | A |
| Keys, tunnel, dashboard | B–C |
| OCR (Apple Vision), maps | D |
| Charts, stats, DuckDB | D2 |
| Image ops, docs, SF Ids | D3 |
| Image **generation** (FLUX 4-bit jobs) | E |
| Salesforce Apex pack + stream downgrade + 1 MB cap | F |
| SIM phone agent (Whisper + TTS + Android bridge) | G |

---

## Near-term product (highest leverage)

### H — Live voice ops console
Dashboard UI for lines, scripts (en / ar-EG / fr), call transcripts, recordings, hangup. Same scopes as Phase G; no new models.

### I — Outbound call campaigns
Job queue of E.164 numbers + one script. Mini places calls **one after another** on the SIM line (fits single Metal slot). Salesforce or CSV upload to start a campaign.

### J — CRM write-back from calls
After a call: create/update Salesforce Case / Lead from transcript (Named Credential already in F). Optional summary via hot Gemma (no exclusive swap).

### K — Messaging agents (no Metal fight)
WhatsApp Business / Telegram text bots using the **same script API** as voice. STT/TTS unused; chat + tools only. Great for Egyptian Arabic support without a phone bridge.

### L — Document inbox
Inbound email or webhook → OCR → Gemma extract → fill CRM fields / return JSON. Libraries first; VLM only when layout needs it.

---

## Model / Metal upgrades (still one slot)

| Idea | Notes |
| --- | --- |
| `gemma4:12b-it-qat` | Quality upgrade **replacing** E4B, never beside it. Measure swap=0. |
| `gpt-oss:20b` exclusive | Heavy reasoning via jobs; unload Gemma first (Phase E plumbing exists). |
| FLUX 8-bit | Opt-in only after measuring peak RAM; 4-bit stays default. |
| Whisper always-warm during a call | `call_session` coresidence experiment if E4B + turbo stay at swap=0. |
| Local TTS experiment | Only after cloud/`edge-tts` path is production; Egyptian Arabic quality is the bar. |

---

## v1.1 from PLAN.md (named, still optional)

- **rembg** — background removal, exclusive GPU like FLUX  
- **sqlite-vec** — local RAG over tenant docs/artifacts  
- **vLLM-metal** — exclusive text experiment in a **separate Python 3.12 venv**; Gemma vision stays on Ollama until proven  
- **Video** — Wan 1.3B experiment only; full video product stays out on 24GB  

---

## Scale-out (when one Mini is not enough)

- **Second Mini** for a second concurrent call / FLUX lane (serialize per box, shard by key or line)  
- Cloudflare Worker gateway (explicitly **not** v1) for edge auth / rate limits in front of multiple appliances  
- Busy-tone / queue depth metrics in `/v1/health` for voice lines  

---

## Explicitly not amazing on this SKU

- Concurrent generative models on one 24GB box  
- Docker Desktop for Ollama/mflux  
- Inference inside Netlify Functions  
- 70B / 120B / `gemma4:26b` / `gemma4:31b` as defaults  
- Face **recognition** (detection may stay opt-in)  
- Replacing Cloudflare Access with a shared admin password  

---

## How to pick the next phase

1. Is it **libraries first**? Prefer that over a new model.  
2. Does it need Metal? If yes, does it fit the exclusive-slot contract?  
3. Does a company pay for it next to Salesforce chat + phone support?  
4. Can it ship without a second Mini?

Default suggestion after F + G are live on the desk: **H (voice console) → J (CRM write-back) → K (WhatsApp/Telegram)** before any new weight download.
