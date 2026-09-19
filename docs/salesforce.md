# Salesforce integration

Apex HTTP callouts default to **10 seconds** and max out at **120 seconds**. The dashboard snippet must always set `req.setTimeout(120000)`. Cumulative callout time per transaction is also 120s.

But 120s is not the real ceiling. Cloudflare's proxy read timeout is about **100 seconds** and is not configurable on the plans this project uses; past that you get a 524 **HTML** page, not JSON. The worker therefore returns its own error at 90s (`PLAN.md` §10, timeout ladder), and the 120000 in Apex is headroom so the error you see is Cloudiator's.

Official:

- Timeouts: https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_timeouts.htm
- Named Credentials: https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_named_credentials.htm
- External Services from OpenAPI: https://developer.salesforce.com/blogs/2025/05/call-third-party-apis-from-an-agent-with-external-service-actions

## Before anything else: Cloudflare must not challenge Apex

Apex cannot run JavaScript, hold cookies, or solve a challenge. If Bot Fight Mode, Browser Integrity Check, Turnstile, or "I'm Under Attack" is on for `api.<domain>`, **every callout from every org fails**, and the Apex-side symptom is a JSON deserialisation error that says nothing about security.

Settings and the required WAF skip rule: `PLAN.md` §13 and `docs/operator-checklist.md` §2a–2b. Verify with:

```bash
curl -s -A 'Salesforce/1.0' -o /tmp/r.txt -w '%{http_code}\n' https://api.<domain>/v1/health
head -c 200 /tmp/r.txt      # must be JSON; if it is <!DOCTYPE html, fix Cloudflare before writing Apex
```

## Named Credential (Phase F)

1. Setup → Named Credentials → **External Credentials** → new, authentication protocol **Custom**.
2. Add a **Principal** (e.g. `CloudiatorPrincipal`). On the principal, add a custom authentication parameter holding the key, e.g. `ApiKey` = `sk-cld-...`.
3. Add a **Custom Header**: `Authorization` = `Bearer {!$Credential.CloudiatorPrincipal.ApiKey}`. Never hardcode the key in Apex.
4. Setup → **Named Credentials** → new, URL `https://api.YOURDOMAIN` (no trailing slash), linked to that External Credential. Enable "Allow formulas in HTTP header".
5. **Create a permission set that grants the running user access to the External Credential Principal, and assign it.** Setup → Permission Sets → your set → External Credential Principal Access → add the principal.
6. Remote Site Settings are not needed when using Named Credentials.

**Step 5 is the one everybody skips.** Without it the callout returns **401** while the exact same key works in `curl`, and nothing in the Apex error mentions permissions. If you are debugging a 401 and the key is good, check step 5 before you check anything else.

## Chat callout

```apex
HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Cloudiator/v1/chat/completions');
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setTimeout(120000);                       // default is 10s; without this you time out mid-thought
req.setBody(JSON.serialize(new Map<String, Object>{
  'model' => 'gemma4:e4b-it-qat',
  'stream' => false,
  'max_tokens' => 512,
  'messages' => new List<Object>{
    new Map<String, Object>{ 'role' => 'user', 'content' => prompt }
  }
}));
HttpResponse res = new Http().send(req);
```

Salesforce keys on Cloudiator **force** `stream=false`. If a request arrives with `stream: true` on such a key, the worker serves a normal JSON response and sets `x-cloudiator-stream-downgraded: true` rather than erroring — External Services can generate Apex that sets `stream`, and failing outright would be worse.

Read the `X-Request-Id` response header and log it. It is the only value that joins your Apex debug log to the Cloudflare log and the Cloudiator usage row.

## Heap, payload, and why you get URLs instead of bytes

Apex synchronous heap is ~6 MB. A large response body throws before your JSON is ever parsed, and the error looks like a platform problem rather than a payload problem.

- The worker enforces `max_response_bytes` (default 1 MB) on keys with `force_no_stream`. Beyond that it returns an artifact URL plus a truncated preview.
- Charts, images, and PDFs are **always** artifact URLs. Never base64.
- **Store the artifact id, not the signed URL.** Signed URLs expire (default 15 minutes). A Flow that writes `result.url` onto a Case produces a dead link by the time anyone opens it. Store the id and call `POST /v1/artifacts/{id}/sign` when you need a fresh URL, within the artifact's retention window.

## Uploading files from Apex

This is genuinely painful and the plan does not pretend otherwise. Hand-rolled `multipart/form-data` in Apex means concatenating base64 blobs with `EncodingUtil` and fighting padding, under a ~6 MB heap.

For Salesforce keys, v1 supports:

- **JSON rows** — the good path. `POST /v1/tools/query` with `{"rows": [...], "sql": "..."}`. Query the records in Apex, serialise, send. No multipart, no encoding tricks.
- **base64 ≤ 1 MB** on `application/json` for a single small file (a scanned invoice for OCR, say).

`multipart/form-data` is supported for non-Apex clients (curl, websites, middleware). Anything larger than ~1 MB from Apex is an integration design problem: push the file to storage the Mini can already reach, or do the upload from middleware, and do not try to solve it inside a trigger.

## Jobs and polling

Images, `gpt-oss:20b`, and anything that may exceed 90s go through the jobs API.

1. `POST /v1/jobs` → `202` `{ "id": "...", "status": "queued" }`. Send an `Idempotency-Key` header — Apex retries a timed-out callout, and without the key you start a second FLUX run.
2. Poll `GET /v1/jobs/{id}`.
3. On `succeeded`, read `result.url` (or `result.artifact_id`) or `result.choices`.

**Polling must be spread across transactions.** "Poll every 5–10s, up to 50 times" is 250–500 seconds of wall clock against a 120s cumulative callout budget — inside one Apex execution it hits the governor limit and fails. Pick one of these:

### Pattern A — Queueable chain with a delay (recommended for Apex-driven work)

A `Queueable implements Database.AllowsCallouts` does one poll, and if the job is still running, re-enqueues itself with a delay. Keep a `depth` field and give up after a documented maximum (e.g. 20 polls). Each execution is its own transaction with its own callout budget.

```apex
public class CloudiatorJobPoller implements Queueable, Database.AllowsCallouts {
    private final String jobId;
    private final Integer depth;
    public CloudiatorJobPoller(String jobId, Integer depth) {
        this.jobId = jobId; this.depth = depth;
    }
    public void execute(QueueableContext ctx) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:Cloudiator/v1/jobs/' + jobId);
        req.setMethod('GET');
        req.setTimeout(120000);
        HttpResponse res = new Http().send(req);
        Map<String, Object> body =
            (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
        String status = (String) body.get('status');

        if (status == 'succeeded' || status == 'failed') {
            handleResult(body);                       // your logic
        } else if (depth < 20) {
            System.enqueueJob(new CloudiatorJobPoller(jobId, depth + 1), 1);  // ~1 min later
        } else {
            handleTimeout(jobId);
        }
    }
}
```

Check the enqueue-with-delay signature against your org's API version; if it is unavailable, fall back to Pattern B.

### Pattern B — Scheduled Flow or scheduled Apex

A record holds the job id and status. A schedulable running every minute picks up outstanding jobs, polls each once, and updates the record. Granularity is one minute, which is fine for a FLUX job that takes 20 seconds plus queue time. This is the most operationally boring option and usually the right one.

### Pattern C — user-driven refresh

A Screen Flow or LWC shows "generating…" with a Refresh button that does one callout. Zero governor risk, and honest about what is happening. Good for interactive work where someone is watching.

Whichever you choose: one poll, one transaction. Do not loop callouts.

## External Services

Download the OpenAPI document with that org's key, using the Salesforce target:

```
GET /v1/openapi.json?target=salesforce
```

That variant emits **OpenAPI 3.0.3** restricted to what the External Services importer reliably accepts (`PLAN.md` §10): no `oneOf`/`anyOf`/`allOf`/`not`, no free-form `additionalProperties`, no recursion, no external `$ref`, `application/json` only, and Apex-safe unique `operationId`s. The plain `/v1/openapi.json` is 3.1 for generic clients and **may not import**.

Only scoped operations appear — a Salesforce-engineer key will not show `/v1/images/generations`.

Smoke-test the import during **Phase B** with a chat-only key. Discovering an importer incompatibility in Phase F, after the generator is finished, is the expensive version of this lesson.

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

Use dashboard preset **Salesforce engineer**: default Gemma E4B QAT only, `max_tokens=512`, `force_no_stream=true`, `max_response_bytes=1MB`, tools ocr/maps/charts/stats/data/docs/text/time/image_ops, no FLUX, no Google, `log_prompts=false`, `GEMMA_THINKING=false`. Arabic and English.

## Data leaving the org

Sending CRM data to a home Mac Mini is a data-processing decision that belongs to the customer, in writing. Prefer tools that keep data on the Mini and never reach a model at all — OCR, DuckDB, stats, charts — over sending contract text into a chat log. `log_prompts=false` is the default and should stay that way.
