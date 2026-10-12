# Cloudiator phone bridge (Android)

Turns a dedicated Android handset + physical SIM into the PSTN radio for the Mac Mini voice agent. **No Twilio / Vonage / DID provider** — you pay for the phone and the SIM only.

## Architecture

```text
Caller --cellular--> Android SIM  --WebSocket PCM 16 kHz-->  Mini FastAPI :8080
                     companion app  <--TTS PCM / control--
```

- Mini API (LAN): `ws://<mini-lan-ip>:8080/v1/voice/lines/{line_id}/media?token=...`
- Control JSON: `ring`, `answer`, `dial`, `hangup`, `busy`, `ended`, `ping`/`pong`
- Media: binary frames of **16-bit little-endian mono PCM at 16 kHz**

Register the line once with a scoped API key:

```bash
curl -s http://127.0.0.1:8080/v1/voice/lines \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"line_id":"desk-1","e164":"+2010xxxxxxx","script":"...","language":"ar-EG","greeting":"أهلاً"}'
# Save the returned token into the app. It is shown once.
```

## Build

Open `android/` in Android Studio (API 26+). Set:

| Pref | Value |
| --- | --- |
| Mini host | LAN IP of the Mac Mini (not the Cloudflare URL) |
| Line id | `desk-1` |
| Line token | from `POST /v1/voice/lines` |
| SIM slot | 0 or 1 |

Prefer a **rooted** handset with Magisk so uplink can use `AudioRecord(VOICE_CALL)` for clean duplex. Without root, enable speakerphone; the mic captures the far side acoustically (degraded).

## Runtime behaviour

1. App connects the media WebSocket and keeps it alive with `ping`.
2. Inbound `ring` → Mini replies `answer` when a script is armed, or `busy`.
3. Outbound: Mini sends `dial` with `to`; app places the GSM call and streams audio.
4. App plays downlink PCM into the call; uploads uplink PCM continuously while active.
5. On remote hangup, app sends `ended`.

## Security

- Media WebSocket is **LAN-only**. Do not put `:8080` on the Cloudflare tunnel for handsets on the same desk network.
- Line token is a shared secret; rotate by re-registering the line.
- The company script API still uses `sk-cld-...` over `https://api.<domain>`.

## Non-goals

- Concurrent calls on one Mini
- Cloud telephony / SIP trunks
- Shipping a Play Store build in this phase (sideload the debug APK)
