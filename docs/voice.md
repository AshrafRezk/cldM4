# Voice intake — scripted calls into Salesforce

Two front doors share one engine, one session store, one commit document, and the same Salesforce Apex:

| Front door | Cost | Speech | Phone number |
| --- | --- | --- | --- |
| **Browser call** (default) | free, no vendor | on the Mini: macOS `say` (TTS) + whisper.cpp on the **CPU** (STT) | none — a link |
| Twilio | Twilio's per-minute price | Twilio `<Say>` / speech recognition | yes |

## Who it is for

Case management, patient support programs, and any call center that onboards customers or records cases: the caller answers a short scripted interview, and the answers land in the CRM as records. The questions are written in Salesforce, not on the Mini.

## Languages and voices

A script lists its `languages` (e.g. `["ar-EG", "en-US"]`); every line has text for each. The call page shows one button per language (**اتصل بالعربي** / **Call in English**); the caller's choice decides what they hear, the language whisper listens for, and the session's `language`.

What the caller hears, per line, in order of preference:

1. **A person's recording** uploaded for that line and language (`PUT /v1/voice/scripts/{id}/recordings/{step}/{lang}`, or a File attached in Salesforce, below).
2. **VoiceTut-TTS** — natural Egyptian Arabic and English ([VoiceTut-TTS](https://huggingface.co/mohammedaly22/VoiceTut-TTS), Apache-2.0, fine-tuned from k2-fsa OmniVoice, Apache-2.0, on ~380 h of Egyptian speech; 19 speakers). Script lines are fixed, so every line is rendered **once, when the script is published**, in the background, on the CPU, in its own venv (`~/Cloudiator/tts-venv`), then the process exits. It never runs during a call and never touches the Metal GPU. Clips are keyed by speaker+language+text, so republishing only renders changed lines. Pick speakers per language with `voices` (`{"ar-EG": "Hadeer", "en-US": "Hadeer"}`; female: Hadeer, Hanan, Mariam, Rana, Sarah, Yasmin, Yara; male: Ahmed, Ali, Hassan, Karim, Mahmoud, Mohammed, Mostafa, Ramy, Shaker, Tareq, Yehia, Youssef).
3. **macOS `say`** (Majed / Samantha) while a render has not landed yet, so a call never waits.

`GET /v1/voice/scripts/{id}/audio` lists every line with its source (`recording`, `rendered`, `fallback`), `ready`/`total`, and the last render error.

## Writing scripts in Salesforce

`salesforce/voice` adds **Cloudiator Voice Script** with child **Cloudiator Voice Question** records:

| Script field | Meaning |
| --- | --- |
| Languages | `ar-EG;en-US` — the call buttons, in order |
| Arabic / English Greeting, Closing | spoken before the first and after the last question |
| Arabic / English Voice | VoiceTut speaker per language |
| Transcript Field | `Case.Description` — receives the whole conversation |
| Fixed Values | one `Object.Field=Value` per line, e.g. `Case.Origin=Phone` |
| Record Links | `Case.ContactId=Contact` — create the Contact first, link the Case to it |

| Question field | Meaning |
| --- | --- |
| Order | sequence |
| Arabic Text / English Text | the question as spoken (write Arabic the way an Egyptian agent says it) |
| Target Field | `Object.Field` the answer fills, e.g. `Contact.MobilePhone`; blank keeps it in the transcript only |
| Required | no answer after the attempts → polite goodbye instead of moving on |
| Attempts | 1–5 |

**Publish Cloudiator voice script** builds the script from those records, writes it to Definition__c (so you can see what was sent), publishes it, and uploads recordings: a File on a Question titled `ar-EG` or `en-US`, or on the Script titled `greeting.ar-EG`, `goodbye.en-US`. **Create Cloudiator voice script from template** makes a ready-to-edit script: `case_intake` (Case with Supplied Name/Phone, Subject), `patient_support` (Contact + Case linked to it), `customer_onboarding` (Lead).

## Browser call

1. Publish a script (`POST /v1/voice/scripts`, below). `inbound_numbers` may be empty.
2. Mint a link: `POST /v1/voice/scripts/{id}/web-link` with a `voice` key. The response `url` (`https://api.cloudiator.org/v1/voice/web/cl_…`) is shown once; only its hash is stored. `POST …/web-link/revoke` kills every link for that script.
3. Anyone with the link opens it, picks a language, allows the microphone, and talks. Each answer is recorded in the browser (silence detection, 16 kHz WAV), transcribed on the Mini, and answered with locally synthesized audio. The finished call is `ready_to_commit` exactly like a Twilio call; `from` is `web`.

The link is the only credential on the page and only starts calls on that one script; it never carries an `sk-cld-` key. Turns are rate limited per client IP (40/min, from `CF-Connecting-IP`), one answer is capped at `VOICE_WEB_MAX_AUDIO_BYTES` (6 MB ≈ 60 s at 48 kHz), and a retried turn replays its cached reply without transcribing again. The page keeps 0.5 s of audio from before speech is detected (so a short name keeps its first syllable), follows the room's noise floor while the caller is silent, and uploads at the microphone's own sample rate; `ffmpeg` on the Mini resamples with a proper filter, and whisper decodes with beam search (`-bs 5`).

**Speech stays off the GPU.** TTS is `say` (`Majed` for Arabic, `Samantha` for English, or the script's `local_voice`), cached under `VOICE_TTS_CACHE` by text+voice, so static prompts are a file read after the first call. STT is `whisper-cli --no-gpu` with `WHISPER_THREADS` CPU threads, one transcription at a time, through `ffmpeg` to 16 kHz mono. It never touches Ollama or the Metal slot. Apple's recognizer is not used: it is on-device for English only and sends Arabic to Apple. Transcripts are normalized before they reach the script: Arabic-Indic digits become 0–9 and dashes/spaces between digits are dropped, so a spoken phone number lands as `01012345678`, not `01-01-2-3-4-5-6-7-8`.

Restart the worker with `scripts/restart-worker.sh` (stop, wait for exit, start, wait for health). `launchctl kickstart -k` races the single-worker boot gate and costs about 90 s of 502s.

Setup: `brew install whisper-cpp` (done on the Mini 2026-11-02) and a ggml model at `WHISPER_MODEL` (default `~/Cloudiator/models/whisper/ggml-large-v3-turbo-q5_0.bin`). Without the model, calls still start and speak, and each answer returns `503 speech_unavailable`.

## Twilio

A Twilio number rings the Mini. The Mini reads a **script published from Salesforce**, speaks with Twilio `<Say>`, hears the caller through Twilio's own speech recognition (`<Gather input="speech">`), and when the script ends produces a **CRM commit document**. Apex in the org inserts those records and acks the session.

Design brief: [claude-code-handoff.md](claude-code-handoff.md). Code: `apps/worker/app/voice/`. Salesforce metadata: [`salesforce/voice/`](../salesforce/voice/README.md).

**What never happens on a call:** Ollama, Gemma, Whisper, mflux, Neon. The webhook path is SQLite and string templates only, so a call cannot take the Metal slot from chat and still answers while Neon is suspended.

## Flow

```
caller ─► Twilio ─► POST /v1/voice/twilio/inbound   (X-Twilio-Signature)
                     ◄─ TwiML: <Say>greeting</Say><Gather action=".../gather?step=ask_name&attempt=1">
          Twilio ─► POST /v1/voice/twilio/gather?step=…&attempt=…   SpeechResult=…
                     ◄─ next <Gather>, a replay, or <Say>goodbye</Say><Hangup/>
session status: in_progress → ready_to_commit (or abandoned)

Salesforce ─► GET  /v1/voice/sessions?status=ready_to_commit     (Bearer sk-cld-, scope voice)
             insert Lead, then Task with WhoId = Lead.Id
           ─► POST /v1/voice/sessions/{id}/ack   {"record_ids": {"Lead": "00Q…", "Task": "00T…"}}
session status: committed
```

## Routes

| Route | Auth | Notes |
| --- | --- | --- |
| `POST /v1/voice/scripts` | Bearer + `voice` | Body is the script JSON, or `{"definition": "<script JSON as a string>"}` (what Apex sends). Returns `{id, version, updated_at}`. A number already routed to **another tenant** is `409 number_in_use`. Within one tenant the latest publish owns the number |
| `GET /v1/voice/scripts` | Bearer + `voice` | `{object: "list", data: [...]}` |
| `GET /v1/voice/sessions[?status=]` | Bearer + `voice` | newest 50, this tenant only |
| `GET /v1/voice/sessions/{id}` | Bearer + `voice` | another tenant's session is 404 |
| `POST /v1/voice/sessions/{id}/ack` | Bearer + `voice` | `record_ids` map, or `records: [{sobject, id}]`. Repeating the same ack is 200; a different one is `409 already_committed`; acking before the call ends is `409 not_ready` |
| `POST /v1/voice/calls` | Bearer + `voice` | `501` — outbound dialing is a later phase |
| `POST /v1/voice/twilio/inbound` | Twilio signature | match `To` to a script's `inbound_numbers`, open a session. Unrouted number → `<Hangup/>` |
| `POST /v1/voice/twilio/gather` | Twilio signature | one webhook per gathered step |
| `POST /v1/voice/twilio/recording` | Twilio signature | optional; stores `RecordingUrl` on the session. Audio is never downloaded to the Mini |

A missing or bad signature is `403 invalid_signature` with a JSON body, never TwiML that continues the script. The signature covers the query string, so a signed `step=ask_name` post cannot be replayed onto another step. The signed URL is rebuilt from `PUBLIC_BASE_URL`; if Twilio and the Mini disagree on that URL, every webhook will 403.

Twilio retries are safe: the reply to each `(CallSid, step, attempt)` is cached, so a retried webhook gets the same TwiML and never appends a second answer.

The Salesforce routes are in the `?target=salesforce` OpenAPI (3.0.3, no composition keywords). Twilio routes are in no OpenAPI document. Session bodies carry the commit document twice: `commit` as an object, and `commit_json` as a string — External Services cannot type sObject field maps, so Apex deserializes `commit_json` untyped.

## Script format

```json
{
  "id": "intake-ar",
  "display_name": "Arabic inbound intake",
  "language": "ar-EG",
  "voice": "Polly.Zeina",
  "inbound_numbers": ["+2010xxxxxxxx"],
  "fail_say": "optional text spoken before hanging up on on_fail=hangup",
  "steps": [
    { "key": "greeting", "say": "مرحباً بك في كلاودياتور. سيتم تسجيل هذه المكالمة.", "gather": false, "next": "ask_name" },
    { "key": "ask_name", "say": "من فضلك قل اسمك الكامل بعد الصافرة.", "gather": true,
      "timeout": 5, "speech_timeout": "auto", "max_attempts": 2, "on_fail": "continue", "next": "ask_reason" },
    { "key": "ask_reason", "say": "ما سبب اتصالك اليوم؟", "gather": true, "max_attempts": 2, "on_fail": "continue", "next": "ask_phone" },
    { "key": "ask_phone", "say": "أكد رقم هاتفك للتواصل.", "gather": true, "max_attempts": 2, "on_fail": "continue", "next": "goodbye" },
    { "key": "goodbye", "say": "شكراً لك. سيتم تسجيل طلبك الآن.", "gather": false, "next": null }
  ],
  "commit": {
    "records": [
      { "sobject": "Lead", "fields": {
          "LastName": "{{ask_name}}", "Company": "Phone Intake", "Phone": "{{ask_phone}}",
          "Description": "{{ask_reason}}\n\n---\n{{transcript}}" } },
      { "sobject": "Task", "after": ["Lead"], "fields": {
          "Subject": "Inbound voice intake", "Status": "Completed",
          "Description": "{{transcript}}", "WhoId": "{{Lead.Id}}" } }
    ]
  }
}
```

Rules the worker enforces on publish (400 with `param` pointing at the problem):

- `id`: letters, digits, `-`, `_`, up to 80. `inbound_numbers`: E.164.
- 1–50 steps, unique `key`s (identifiers; `transcript`, `from`, `to`, `call_sid` are reserved). `next` must name a step or be `null`; loops are rejected.
- `timeout` 1–60 s (default 5), `max_attempts` 1–5 (default 2), `on_fail` `continue` (store empty, move on) or `hangup` (speak `fail_say` or a default, hang up, session `abandoned`).
- `language` is passed to both `<Say>` and `<Gather>` (default `en-US`). `voice` is any Twilio voice name; omit it for Twilio's default.
- `commit.records`: one record per sObject type, field API names mapped to text templates, `after` may only name records listed earlier.

Templates: `{{step_key}}` → the trimmed answer (empty if none). `{{transcript}}` → `Agent: …` / `Caller: …` lines. `{{from}}`, `{{to}}`, `{{call_sid}}` → the call. `{{SObject.Id}}` is left as-is for Apex to replace after that parent is inserted. Substitution is a single pass: a caller who says `{{ask_phone}}` gets those characters, not another field. Each value is capped at 32768 characters; Apex truncates further to the field length.

## Operator steps

1. `~/Cloudiator/.env`: set `TWILIO_AUTH_TOKEN` (Twilio Console → Account → Auth Token). Optional: `VOICE_DB`, `VOICE_SESSION_TTL_DAYS`. `chmod 600`, restart the worker LaunchAgent. Never commit the token.
2. Twilio number → Voice configuration → "A call comes in": Webhook, `POST https://api.cloudiator.org/v1/voice/twilio/inbound`. The gather URL comes back inside TwiML; nothing else to configure.
3. Cloudflare: Bot Fight Mode / Browser Integrity Check must not challenge `api.cloudiator.org` — Twilio, like Apex, fails on an HTML interstitial ([operator-checklist.md](operator-checklist.md) §2).
4. Mint a key with `voice` (preset `voice_intake` = `chat` + `voice`; `salesforce_engineer` now includes `voice`).
5. Deploy [`salesforce/voice`](../salesforce/voice/README.md), publish a script, place a call, check `GET /v1/voice/sessions?status=ready_to_commit`, run the Commit action, confirm the Lead and Task, confirm the session shows `committed`.

Smoke test without a phone, from the Mini (signature computed with the same token):

```bash
cd apps/worker && .venv/bin/python - <<'PY'
import os, urllib.parse, httpx
from app.voice.twilio_sig import compute_signature
base = os.environ["PUBLIC_BASE_URL"].rstrip("/"); token = os.environ["TWILIO_AUTH_TOKEN"]
form = {"CallSid": "CAsmoke1", "From": "+201000000000", "To": "+2010xxxxxxxx"}
url = base + "/v1/voice/twilio/inbound"
r = httpx.post(url, data=form, headers={"X-Twilio-Signature": compute_signature(token, url, form.items())})
print(r.status_code, r.text[:300])
PY
```

## Privacy and retention

Transcripts are treated as prompts. The worker never writes them to its log (only session id, script id, and status). Sessions — answers, transcript, commit document, recording URL — are deleted `VOICE_SESSION_TTL_DAYS` (7) after ack, or 7 days after the last update for a call that was never acked. The purge runs on each new inbound call.

## Not in this slice

- Outbound dialing / campaigns (`POST /v1/voice/calls` is a 501 stub).
- Turning on call recording from TwiML. The `recording` webhook is ready; recording itself is enabled on the Twilio side if wanted.
- Whisper or Gemma on the call path, Mini-side Salesforce writes, a dashboard script editor, Android/SIM bridge.

## Verification status

- Worker: hermetic pytest (`apps/worker/tests/test_voice_*.py`) covers publish → signed inbound → gathers → `ready_to_commit` → ack, Twilio retry idempotency, silence replay, `on_fail`, bad signature, tenant isolation, and the Salesforce OAS composition check.
- Apex in `salesforce/voice/` has a mock-callout test class but has **not** been compiled or run in an org yet. First deploy to a sandbox with `--test-level RunSpecifiedTests --tests CloudiatorVoiceTest`.
- No live Twilio call has been placed yet.
