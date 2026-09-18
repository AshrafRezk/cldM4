# Salesforce integration

Apex HTTP callouts default to **10 seconds** and max out at **120 seconds**. The dashboard snippet must always set `req.setTimeout(120000)`. Cumulative callout time per transaction is also 120s.

Official:

- Timeouts: https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_timeouts.htm
- Named Credentials: https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_named_credentials.htm
- External Services from OpenAPI: https://developer.salesforce.com/blogs/2025/05/call-third-party-apis-from-an-agent-with-external-service-actions

## Named Credential (Phase F)

1. Setup → Named Credentials → External Credentials → Custom / Header.
2. Header `Authorization` = `Bearer sk-cld-...` (store as a secret; do not hardcode in Apex).
3. Named Credential URL = `https://api.YOURDOMAIN` (no trailing slash).
4. Enable “Allow formulas in HTTP header” if using merge fields.
5. Remote Site Settings are skipped when using Named Credentials.

## Chat callout

```apex
HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Cloudiator/v1/chat/completions');
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setTimeout(120000);
req.setBody(JSON.serialize(new Map<String, Object>{
  'model' => 'qwen3.5:9b',
  'stream' => false,
  'max_tokens' => 512,
  'messages' => new List<Object>{
    new Map<String, Object>{ 'role' => 'user', 'content' => prompt }
  }
}));
HttpResponse res = new Http().send(req);
```

Salesforce keys on Cloudiator **force** `stream=false`. Do not send 10MB base64 images into Apex heap; send a public/signed artifact URL or a Job id.

## Jobs (image, heavy chat)

1. `POST /v1/jobs` → `{ "id": "...", "status": "queued" }` (HTTP 202).
2. Flow scheduled path or Wait: `GET /v1/jobs/{id}` every 5–10s, max ~50 polls.
3. On `succeeded`, read `result.url` or `result.choices`.

Keep each poll as its own transaction if you are near the 120s cumulative cap.

## External Services

Download `GET /v1/openapi.json` with that org’s key (or from the dashboard). Import into External Services. Only scoped operations appear — a Salesforce-engineer key will not show `/v1/images/generations`.

## Heap and payload

- Apex heap is small; return chart/image **URLs**, not PNG bytes.
- JSON body for CSV: prefer uploading to `/v1/tools/query` as multipart from a middleware if the CSV is large; or chunk. Salesforce max request size still applies.

## 15-character to 18-character Id

Salesforce case-insensitive IDs need the 3-character suffix. Implement in `apps/worker/tools/salesforce/ids.py`:

```python
def to_18(id15: str) -> str:
    id15 = id15.strip()
    if len(id15) == 18:
        return id15
    if len(id15) != 15:
        raise ValueError("Salesforce id must be 15 or 18 chars")
    suffix = []
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    for block in range(3):
        flags = 0
        for bit in range(5):
            c = id15[block * 5 + bit]
            if "A" <= c <= "Z":
                flags |= 1 << bit
        suffix.append(alphabet[flags])
    return id15 + "".join(suffix)
```

Reference: https://salesforce.stackexchange.com/questions/27668

## Preset

Use dashboard preset **Salesforce engineer**: 9B only, `max_tokens=512`, `force_no_stream=true`, tools ocr/maps/charts/stats/data/docs/text/time/image_ops, no FLUX, no Google, `log_prompts=false`.
