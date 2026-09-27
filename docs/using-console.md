# Using minting and the playground

Phases A–E are on `main`. This page is how you use what they shipped: mint a scoped key at `https://app.cloudiator.org/console`, send a chat from the playground, and call every live tool with that key. Secrets stay in the password manager. What is still unfinished is [next-steps.md](next-steps.md).

The console has no login form and no shared password. Cloudflare Access challenges the browser. An incognito window that is not signed in to Access stops on Access, before this app.

## 1. Mint a key in the browser

1. Open `https://app.cloudiator.org/console`.
2. Under **Tenants**, enter a slug (`acme`, pattern `[a-z0-9][a-z0-9-]{1,62}`) and a name, then **Create tenant**. Select the tenant.
3. Under **Mint key**, pick a preset, tick the scopes you want, and press **Mint key**.
4. The plaintext `sk-cld-…` key is shown **once**. Copy it into the password manager. A refresh cannot show it again. Neon stores an argon2id hash.
5. The Playground tab opens with that key already filled in.

Presets come from `packages/schema/scopes.json`. Tick extra checkboxes when a preset omits a tool you need.

| Preset | What the key can do |
| --- | --- |
| Salesforce engineer | Chat, embeddings, OCR, maps, charts, stats, DuckDB, documents, text, holidays, image ops. Stream is forced off. Response cap is 1 MB. |
| Creative | Chat, embeddings, FLUX image jobs, diagrams, OCR, image ops. |
| Analyst | Chat, embeddings, charts, stats, DuckDB, documents, text. |
| Heavy | Chat and embeddings only. `gpt-oss:20b` is not installed. |
| Speech | Checkboxes only. Transcription and audio routes are not in v1. |

These mint-form checkboxes have no route yet: `transcriptions`, `tools.audio_ops`, `tools.fx`, `tools.google_places`, `tools.face_detect`.

**Revoke** is on the selected key. It takes up to 60 seconds because the Mini caches key lookups. On the Mini, `POST http://127.0.0.1:8080/v1/admin/cache/flush` makes it immediate.

**Download OpenAPI JSON** is the key's scoped spec. **Salesforce (External Services)** is the same spec with `?target=salesforce` (OpenAPI 3.0.3). The Salesforce tab on the console has the Named Credential steps and the Apex snippet (`setTimeout(120000)`, `"stream": false`).

The **Usage** tab reads `usage_daily`. A chat can take about 15 seconds to appear, after the Mini flushes its outbox.

### Same mint from the Mini

The dashboard is the normal path. The CLI prints the same one-time secret:

```bash
cd /Users/ashrafrezk/cldM4/apps/worker
.venv/bin/python -m app.dbtool mint-key \
  --tenant cloudiator --name 'Playground' --preset salesforce_engineer
.venv/bin/python -m app.dbtool revoke-key <public_id>
```

The CLI reads `/Users/ashrafrezk/Cloudiator/.env` itself. Do not `source` that file.

## 2. Playground

Stay on `https://app.cloudiator.org/console`, tab **Playground**.

- Paste `sk-cld-…` if this browser session is not the one that just minted the key.
- The box starts with an Arabic sentence. Replace it with any message. Send.
- The browser POSTs to `https://api.cloudiator.org/v1/chat/completions` with `stream: false`, `max_tokens: 512`, and model `gemma4:e4b-it-qat`. Netlify does not run the model.
- The button waits up to 90 seconds, then says the worker deadline was hit.
- A reply is the model's text. A red line is the worker's error (`401` bad key, `403` missing scope, `429` rate limit).

When the request omits a `tools` array, the worker attaches the chat tools this key is allowed to use, and FastAPI runs them (at most 8 calls, 75 seconds). Ask in plain language and the model can call them. Example: "Geocode Cairo, Egypt and do not invent the coordinates."

Chat tools the worker may attach, if the key has the scope:

| Tool the model calls | Scope | What you get |
| --- | --- | --- |
| `ocr_image` | `tools.ocr` | Text from an https or `data:image` URL |
| `geocode` | `tools.maps` | Latitude and longitude for one place |
| `places_nearby` | `tools.maps` | OSM amenities near a point |
| `render_chart` | `tools.charts` | PNG URL (matplotlib) |
| `stats_describe` | `tools.stats` | count, mean, std, min, quartiles, max |
| `sql_on_table` | `tools.data` | One SELECT over CSV you supplied |
| `extract_document` | `tools.docs` | Text from a PDF, DOCX, XLSX, or TXT |
| `image_transform` | `tools.image_ops` | Convert, QR, EXIF, or palette |
| `fuzzy_match` | `tools.text` | Closest strings from a list you supplied |
| `convert_units` | `tools.units` | A converted number |
| `render_diagram` | `tools.diagrams` | Graphviz PNG URL |

A Salesforce-engineer key includes maps, OCR, charts, stats, data, docs, text, and image ops. It does not include diagrams, unit conversion, or FLUX. Tick those scopes, or mint **Creative** for diagrams and image jobs.

## 3. Call a tool directly

Use this when you want a specific result and do not want the model to choose. From any machine that can reach the API (the Air is fine). Set `KEY` to the minted secret.

```bash
export KEY='sk-cld-…'
export API=https://api.cloudiator.org
```

Every call sends `Authorization: Bearer $KEY` and `content-type: application/json`. A missing scope is HTTP 403 `scope_denied`.

### Chat and embeddings

```bash
curl -s "$API/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model":"gemma4:e4b-it-qat","stream":false,"max_tokens":64,"messages":[{"role":"user","content":"اكتب جملة واحدة بالفصحى عن الطقس."}]}'

curl -s "$API/v1/embeddings" \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model":"nomic-embed-text","input":"Cairo"}'

curl -s "$API/v1/models" -H "Authorization: Bearer $KEY"
```

`GET /v1/models` lists tags that are on the Mini and allowed for this key.

### Library tools (no extra model)

OCR — file upload, or JSON `image_url` (https or `data:image`) or `image_base64`:

```bash
curl -s "$API/v1/tools/ocr" -H "Authorization: Bearer $KEY" \
  -F file=@invoice.png
```

```bash
curl -s "$API/v1/tools/geocode" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"q":"Cairo, Egypt"}'

curl -s "$API/v1/tools/places" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"lat":30.0444,"lon":31.2357,"kind":"cafe"}'

curl -s "$API/v1/tools/route" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"origin_lat":30.0444,"origin_lon":31.2357,"destination_lat":30.0131,"destination_lon":31.2089}'

curl -s "$API/v1/tools/chart" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"kind":"bar","title":"Fruit","x":["apples","pears"],"series":[{"name":"qty","values":[5,4]}]}'

curl -s "$API/v1/tools/stats" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"action":"describe","values":[1,2,3,4,5]}'

curl -s "$API/v1/tools/query" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"sql":"SELECT kind, SUM(qty) AS qty FROM data GROUP BY kind","csv":"kind,qty\napples,2\napples,3\npears,4"}'

curl -s "$API/v1/tools/text" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"action":"sf_id","id":"001D000000IRt53"}'

curl -s "$API/v1/tools/time" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"country":"EG","date":"2026-01-07"}'

curl -s "$API/v1/tools/units" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"value":5,"from_unit":"kilometer","to_unit":"meter"}'

curl -s "$API/v1/tools/diagram" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"source":"digraph G { A -> B }","engine":"graphviz"}'
```

Other bodies the same routes accept:

| Route | Scope | Extra bodies |
| --- | --- | --- |
| `POST /v1/tools/stats` | `tools.stats` | `action` is `describe` (needs `values`), `ttest` (needs `a` and `b`, at least two numbers each), `ols` (needs `y` and `x`), `monte_carlo` (`n`, `mean`, `std`, `seed`), or `npv` (`rate`, `cashflows`). |
| `POST /v1/tools/text` | `tools.text` | `action` `fuzzy` with `query` and `choices`; `phone` with `number` and `region` (2 letters, default `US`); `sf_id` with `id`. |
| `POST /v1/tools/image` | `tools.image_ops` | `action` is `convert`, `qr_encode`, `qr_decode`, `exif`, or `palette`. `qr_encode` needs `text`. The others need `image_base64`. `convert` takes `format` `jpeg`, `png`, or `heic`. GPS is stripped unless `strip_gps` is false. |
| `POST /v1/tools/document` | `tools.docs` | `filename` ending in `pdf`, `docx`, `xlsx`, or `txt`, plus `file_base64`. A long file returns a preview and an artifact URL. |
| `POST /v1/tools/query` | `tools.data` | `sql` plus `csv`, or `columns` and `rows`. One statement. The table name defaults to `data`. |

`route` and `time` are REST only. The playground model is not given those two tools. Stats actions other than `describe`, and text actions other than fuzzy match, are also REST-only.

Chart, diagram, document, and image routes can return a signed URL on `https://api.cloudiator.org/artifacts/…`. The signature expires (default 15 minutes). Keep the artifact id and re-mint:

```bash
curl -s -X POST "$API/v1/artifacts/ARTIFACT_ID/sign" -H "Authorization: Bearer $KEY"
```

### FLUX image jobs

Mint a key with the **Creative** preset (`image_generation`). A 1024² generate takes about two minutes and uses the single Metal slot, so chat waits until it finishes. The worker unloads Gemma, runs 4-bit schnell with `--low-ram`, then reloads Gemma.

```bash
JOB=$(curl -s -X POST "$API/v1/jobs" \
  -H "Authorization: Bearer $KEY" \
  -H 'Idempotency-Key: bicycle-1' \
  -H 'content-type: application/json' \
  -d '{"kind":"image","prompt":"a red bicycle"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -s "$API/v1/jobs/$JOB" -H "Authorization: Bearer $KEY"
```

The first response is HTTP 202 with `status` `queued`. Poll until `status` is `succeeded`. `result.url` is the signed PNG. The same `Idempotency-Key` within 24 hours returns the original job. `POST /v1/images/generations` with `{"prompt":"a red bicycle"}` enqueues the same kind of job. `kind` must be `image`. `n` must be 1. Optional fields: `size` (for example `1024x1024`), `seed`, `steps` from 1 to 4.

## 4. What a good call looks like

These already ran on the Mini on 2026-09-27. Repeat them with your own key when you want to see the live appliance:

| Call | Result that proved the phase |
| --- | --- |
| OCR on a large-font PNG | `{"text":"INVOICE 42"}` |
| Geocode `Cairo, Egypt` | `30.0443879, 31.2357257`; the repeat was `0.005s` from the cache |
| Fruit CSV `SUM` by kind | apples 5, pears 4 |
| Chart | `engine: matplotlib` and a signed PNG URL |
| `sf_id` `001D000000IRt53` | `001D000000IRt53IAD` |
| Diagram with `engine: mermaid` | Rendered with Graphviz (`/opt/homebrew/bin/dot`) |
| FLUX job `dcbfbc7dc5af4e7e91967a7e5c057496` | `succeeded`, artifact `8034c949723d4c1caca9c7838abfbb06` |

After a playground send, open the **Usage** tab and refresh. Today's row is the confirmation the outbox reached Neon.
