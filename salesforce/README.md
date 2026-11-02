# Cloudiator Salesforce unmanaged app

Installable **unmanaged** metadata (no namespace) that turns a minted `sk-cld-…` key into a plug-and-play Salesforce app:

- **Cloudiator** Lightning app (App Manager)
- **Setup** tab — paste API key into protected hierarchy custom setting `Cloudiator_Config__c`
- **Home** — service catalog, quick chat, recent call logs
- **Call Logs** — `Cloudiator_Call_Log__c` (service, success/failure, modalities, `X-Request-Id`, truncated I/O, artifact id)
- **Flow actions** under category **Cloudiator** (chat, embeddings, OCR, geocode, research, chart, stats, query, document, text, time, image ops, job create/poll)
- Apex service layer for custom code

Outbound auth is **Bearer API key** (Named Credential / External Credential preferred, or protected custom setting + Remote Site). This is **not** a Salesforce Connected App — Connected Apps are for OAuth *into* Salesforce; Cloudiator callouts go the other way.

## Install (org)

**Preferred:** https://app.cloudiator.org/console → **Salesforce** → **Connect Salesforce & install** (Production or Sandbox). Requires Netlify env `SF_OAUTH_CLIENT_ID` + `SF_OAUTH_CLIENT_SECRET` (see [docs/salesforce-app.md](../docs/salesforce-app.md)).

CLI fallback:

```bash
cd salesforce
sf org login web --alias myorg
sf project deploy start --source-dir force-app --target-org myorg
sf org assign permset --name Cloudiator_Admin --target-org myorg
```

Or zip deploy:

```bash
./scripts/pack-salesforce-unmanaged.sh
# Upload dist/cloudiator-salesforce-unmanaged.zip via Workbench → Deploy
```

## After deploy

1. Mint **Salesforce engineer** key at https://app.cloudiator.org/console  
2. App Launcher → **Cloudiator** → **Cloudiator Setup** → paste key → **Test /v1/health**  
3. (Recommended) Create Named Credential `Cloudiator` + External Credential principal per [docs/salesforce.md](../docs/salesforce.md), assign principal permission set, then tick **Use Named Credential** in Setup.  
4. Import External Services from `GET /v1/openapi.json?target=salesforce` (OpenAPI **3.0.3**) if you want schema-driven actions in addition to packaged Flow invocables.  
5. Build Flows with **Cloudiator:*** actions; inspect **Cloudiator Call Logs**.

## Modalities

| In → Out | Services |
| --- | --- |
| Text → Text | Chat, Research, Stats, Query, Text tools, Time, Geocode, Embeddings |
| Image → Text | OCR |
| Text → Image | Chart (artifact URL); FLUX jobs if key has `image_generation` |
| Image → Image | Image ops |
| Binary → Mixed | Document extract/render |
| Audio | **Not in v1 engineer preset** (Whisper / Phase G later). Leave Speech scopes off until the Mini exposes `/v1/audio/*`. |

Full console guide: Console → **Salesforce** tab after this ships, and [docs/salesforce-app.md](../docs/salesforce-app.md).
