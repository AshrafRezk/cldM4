# Cloudiator Salesforce unmanaged app

Operator-facing guide for the installable package under [`salesforce/`](../salesforce/). Console UI: **App → Console → Salesforce**.

## What you get

| Piece | Purpose |
| --- | --- |
| Lightning app **Cloudiator** | App Manager entry with Home, Setup, Call Logs |
| `Cloudiator_Config__c` | Protected hierarchy setting: API key, base URL, default model |
| `Cloudiator_Call_Log__c` | Every Flow/Apex/UI call: success/failure, modalities, `X-Request-Id`, I/O |
| Flow actions (`Cloudiator:*`) | Chat, embeddings, tools, jobs |
| Apex `CloudiatorService` | Same operations for custom classes |

**Salesforce calls Cloudiator** (outbound Bearer / Named Credential). That is the product. Install OAuth is only so Cloudiator can *deploy* metadata into the org; callouts afterward are org → `api.cloudiator.org`.

## Install from the Console (no Netlify secrets)

You should **not** put a Salesforce client secret in Netlify.

1. Select a key (or mint a new **Salesforce engineer** key).  
2. **Salesforce** tab → paste the full `sk-cld-…` secret (fresh mint is filled automatically; existing keys come from your password manager).  
3. Production or Sandbox → **Install & connect** (first time) or **Connect existing key only** (org already has the app).  
4. Log into the target org on Salesforce.  
5. Cloudiator deploys if needed, assigns **Cloudiator Admin**, and writes the key into org Setup.  
6. App Launcher → **Cloudiator** → Flows / Apex. Salesforce calls the Mini.

### One-time product config (public ids only)

Edit [`apps/dashboard/netlify/functions/_lib/sfInstallConfig.json`](../apps/dashboard/netlify/functions/_lib/sfInstallConfig.json) and commit (or set the same names as optional Netlify env — still **not** secrets):

| Field | What |
| --- | --- |
| `SF_PACKAGE_VERSION_ID` | Preferred. `04t…` from a package you publish once. Install button opens Salesforce’s own installer. |
| `SF_OAUTH_CLIENT_ID` | Alternative. Public **Consumer Key** of a Connected App / External Client App with **PKCE** (no consumer secret). Callback: `https://app.cloudiator.org/api/salesforce/oauth/callback`. Scopes: `api`, `refresh_token`. |

Create that Connected App once in any DE org you control (Cloudastick). End users of Cloudiator never see it.

### CLI / zip fallback

See [salesforce/README.md](../salesforce/README.md).

## API contract (Salesforce OpenAPI 3.0.3)

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

Rules: `stream` forced off; `setTimeout(120000)`; store artifact ids; one job poll per transaction; **audio** not on engineer OpenAPI yet.

## Call logs

Object **Cloudiator Call Log** — written by `CloudiatorService` and all invocables.

## Apex

```apex
CloudiatorService.Result r = CloudiatorService.chat('Say hello in one short sentence.', null, 128, null);
System.debug(r.requestId + ' ' + r.text);
```
