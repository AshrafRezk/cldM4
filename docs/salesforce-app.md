# Cloudiator Salesforce unmanaged app

Operator-facing guide for the installable package under [`salesforce/`](../salesforce/). Console UI: **App → Console → Salesforce**.

## What you get

| Piece | Purpose |
| --- | --- |
| Lightning app **Cloudiator** | App Manager entry with Home, Setup, Call Logs |
| `Cloudiator_Config__c` | Protected hierarchy setting: API key, base URL, default model, Named Credential flag |
| `Cloudiator_Call_Log__c` | Every Flow/Apex/UI call: service, success/failure, modalities, HTTP status, `X-Request-Id`, truncated I/O, artifact id |
| Flow actions (`Cloudiator:*`) | Chat, embeddings, tools, jobs |
| Apex `CloudiatorService` | Same operations for custom classes |
| Remote Site `Cloudiator_API` | `https://api.cloudiator.org` (fallback when not using Named Credential) |

**Not a Connected App.** Outbound callouts use Bearer `sk-cld-…` via External Credential / Named Credential (recommended) or the protected setting. Connected Apps are for inbound OAuth into Salesforce.

## Install

### One-click from the Console (preferred)

1. Operator (once): create a Salesforce **External Client App / Connected App** used only for install OAuth (not for callouts).  
   - Callback URL: `https://app.cloudiator.org/api/salesforce/oauth/callback`  
   - Selected OAuth scopes: **Manage user data via APIs (api)**, **Perform requests at any time (refresh_token)**  
   - Enable web server flow; require secret  
2. Netlify site env (server only):

| Name | Purpose |
| --- | --- |
| `SF_OAUTH_CLIENT_ID` | Connected App consumer key |
| `SF_OAUTH_CLIENT_SECRET` | Connected App consumer secret |
| `SF_PACKAGE_VERSION_ID` | optional `04t…` — if set, the button opens Salesforce’s native package installer instead of Metadata deploy |

3. User at https://app.cloudiator.org/console → **Salesforce** → choose Production or Sandbox → **Connect Salesforce & install**.  
4. Log into the target org → Cloudiator deploys `salesforce/force-app` via Metadata API and tries to assign **Cloudiator Admin**.  
5. Mint a **Salesforce engineer** key → in the org open **Cloudiator Setup** → paste key → **Test /v1/health**.

CLI / Workbench: [salesforce/README.md](../salesforce/README.md).

## Mint → configure (plug and play)

1. https://app.cloudiator.org/console → tenant → mint preset **Salesforce engineer** (copy plaintext once).  
2. Install via the Console button (above) or CLI.  
3. Salesforce App Launcher → **Cloudiator** → **Cloudiator Setup** → paste key → Save → **Test /v1/health**.  
4. Optional hardening: create Named Credential `Cloudiator` + External Credential principal ([salesforce.md](salesforce.md) §Named Credential), grant principal access, enable **Use Named Credential** in Setup.

The package cannot invent your key. Minting stays on Cloudiator; the org only stores what you paste.

## API contract (Salesforce OpenAPI 3.0.3)

Download with the org key:

```http
GET /v1/openapi.json?target=salesforce
Authorization: Bearer sk-cld-…
```

Also: Console → key → **Salesforce (External Services)**.

### Operations (Salesforce engineer preset)

| Method | Path | Flow action | In → Out |
| --- | --- | --- | --- |
| POST | `/v1/chat/completions` | Cloudiator: Chat | Text → Text |
| POST | `/v1/embeddings` | Cloudiator: Embeddings | Text → Binary |
| POST | `/v1/tools/ocr` | Cloudiator: OCR | Image → Text |
| POST | `/v1/tools/geocode` | Cloudiator: Geocode | Text → Text |
| POST | `/v1/tools/research` | Cloudiator: Research | Text → Text |
| POST | `/v1/tools/chart` | Cloudiator: Chart | Text → Image (artifact) |
| POST | `/v1/tools/stats` | Cloudiator: Stats | Text → Text |
| POST | `/v1/tools/query` | Cloudiator: Query | Text → Text |
| POST | `/v1/tools/document` | Cloudiator: Document | Binary → Mixed |
| POST | `/v1/tools/text` | Cloudiator: Text tools | Text → Text |
| POST | `/v1/tools/time` | Cloudiator: Time | Text → Text |
| POST | `/v1/tools/image` | Cloudiator: Image ops | Image → Image |
| POST | `/v1/jobs` | Cloudiator: Create image job | Text → job id (needs `image_generation`) |
| GET | `/v1/jobs/{id}` | Cloudiator: Poll job | — → status / artifact |
| GET | `/v1/health` | (Home / Setup test) | — → JSON |

Rules that matter for Apex:

- `stream` is forced off (`x-cloudiator-stream-downgraded` if client sent true).  
- `setTimeout(120000)`; Cloudflare ~100s; worker fails closed ~90s.  
- Store **artifact ids**, not signed URLs.  
- One job poll per transaction (Queueable / scheduled / user refresh).  
- **Audio** is not exposed on the engineer OpenAPI yet (Phase G / Whisper).

## Call logs

Object **Cloudiator Call Log**. Fields: Service, Status, Modality In/Out, HTTP Status, Request Id, Duration, Input/Output summaries, Error, Artifact Id, Related Record Id.

Logged automatically from `CloudiatorService` and all invocables.

## Apex snippets

Packaged classes under `salesforce/force-app/.../classes/`. Minimal Anonymous Apex after Setup:

```apex
CloudiatorService.Result r = CloudiatorService.chat('Say hello in one short sentence.', null, 128, null);
System.debug(r.requestId + ' ' + r.text);
```

OCR (image URL or base64 in JSON body per OpenAPI):

```apex
Map<String, Object> body = new Map<String, Object>{ 'image_url' => 'https://example.com/invoice.png' };
CloudiatorService.Result r = CloudiatorService.tool('OCR', '/v1/tools/ocr', body, 'Image', 'Text', null);
System.debug(r.body);
```

See also `examples/salesforce/` for Named Credential–only chat + job poller samples.
