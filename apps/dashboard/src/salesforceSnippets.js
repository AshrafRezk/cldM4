export const DEFAULT_MODEL = "gemma4:e4b-it-qat";

/** Service catalog for console guide + package parity. */
export const SERVICES = [
  {
    id: "chat",
    name: "Chat",
    path: "POST /v1/chat/completions",
    flow: "Cloudiator: Chat",
    modality: "Text → Text",
    body: {
      model: DEFAULT_MODEL,
      stream: false,
      max_tokens: 512,
      messages: [{ role: "user", content: "hi" }],
    },
  },
  {
    id: "embeddings",
    name: "Embeddings",
    path: "POST /v1/embeddings",
    flow: "Cloudiator: Embeddings",
    modality: "Text → Binary",
    body: { model: "nomic-embed-text", input: "hello" },
  },
  {
    id: "ocr",
    name: "OCR",
    path: "POST /v1/tools/ocr",
    flow: "Cloudiator: OCR",
    modality: "Image → Text",
    body: { image_url: "https://example.com/invoice.png" },
  },
  {
    id: "geocode",
    name: "Geocode",
    path: "POST /v1/tools/geocode",
    flow: "Cloudiator: Geocode",
    modality: "Text → Text",
    body: { q: "Cairo, Egypt" },
  },
  {
    id: "research",
    name: "Research",
    path: "POST /v1/tools/research",
    flow: "Cloudiator: Research",
    modality: "Text → Text",
    body: { query: "Cloudflare Access JWT audience" },
  },
  {
    id: "chart",
    name: "Chart",
    path: "POST /v1/tools/chart",
    flow: "Cloudiator: Chart",
    modality: "Text → Image (artifact)",
    body: {
      type: "bar",
      title: "Fruit",
      data: { labels: ["apples", "pears"], values: [5, 4] },
    },
  },
  {
    id: "stats",
    name: "Stats",
    path: "POST /v1/tools/stats",
    flow: "Cloudiator: Stats",
    modality: "Text → Text",
    body: { rows: [{ n: 1 }, { n: 2 }, { n: 3 }], op: "describe", column: "n" },
  },
  {
    id: "query",
    name: "Query (DuckDB)",
    path: "POST /v1/tools/query",
    flow: "Cloudiator: Query",
    modality: "Text → Text",
    body: {
      rows: [
        { fruit: "apples", qty: 5 },
        { fruit: "pears", qty: 4 },
      ],
      sql: "select fruit, sum(qty) as qty from rows group by 1",
    },
  },
  {
    id: "document",
    name: "Document",
    path: "POST /v1/tools/document",
    flow: "Cloudiator: Document",
    modality: "Binary → Mixed",
    body: { action: "extract", filename: "note.txt", content_base64: "aGVsbG8=" },
  },
  {
    id: "text",
    name: "Text tools",
    path: "POST /v1/tools/text",
    flow: "Cloudiator: Text tools",
    modality: "Text → Text",
    body: { op: "fuzzy", query: "cairo", choices: ["Cairo", "Alexandria"] },
  },
  {
    id: "time",
    name: "Time / holidays",
    path: "POST /v1/tools/time",
    flow: "Cloudiator: Time",
    modality: "Text → Text",
    body: { op: "now", tz: "Africa/Cairo" },
  },
  {
    id: "image_ops",
    name: "Image ops",
    path: "POST /v1/tools/image",
    flow: "Cloudiator: Image ops",
    modality: "Image → Image",
    body: { op: "qr", text: "https://app.cloudiator.org" },
  },
  {
    id: "jobs",
    name: "Image job (FLUX)",
    path: "POST /v1/jobs + GET /v1/jobs/{id}",
    flow: "Cloudiator: Create image job / Poll job",
    modality: "Text → Image (async)",
    note: "Requires image_generation on the key. Engineer preset excludes FLUX — mint a wider key or add scope.",
    body: { kind: "image", prompt: "a red bicycle" },
  },
  {
    id: "audio",
    name: "Audio / speech",
    path: "—",
    flow: "—",
    modality: "Audio → Text (later)",
    note: "Not in v1 OpenAPI / engineer preset. Whisper lands with Phase G; do not promise /v1/audio yet.",
    body: null,
  },
];

export function namedCredentialSteps(apiUrl) {
  return [
    "Setup → Named Credentials → External Credentials → New, protocol Custom.",
    "Add a Principal (e.g. CloudiatorPrincipal). Parameter ApiKey = the sk-cld- key (shown once when minted).",
    "Custom Header: Authorization = Bearer {!$Credential.CloudiatorPrincipal.ApiKey}. Never hardcode the key in Apex.",
    `Named Credentials → New, name Cloudiator, URL ${apiUrl} (no trailing slash), link External Credential, allow formulas in HTTP header.`,
    "Permission set → External Credential Principal Access → add the principal → assign to running users. Skip this and Apex 401s while curl works.",
    "Optional: install the unmanaged app (salesforce/) and enable Use Named Credential in Cloudiator Setup.",
  ];
}

export function installSteps() {
  return [
    "Mint a Salesforce engineer key, or keep an existing sk-cld-… in your password manager.",
    "Console → Salesforce → paste the key → Install & connect (or Connect existing key only if the org already has the app).",
    "Fallback: deploy salesforce/force-app with Salesforce CLI or scripts/pack-salesforce-unmanaged.sh → Workbench, then assign Cloudiator Admin.",
    "App Launcher → Cloudiator → Cloudiator Setup → confirm key + base URL → Test /v1/health.",
    "Build Flows with Cloudiator:* actions; open Cloudiator Call Logs for success/failure + X-Request-Id.",
    "Optional: import External Services from the Salesforce OpenAPI download below (3.0.3).",
  ];
}

export function apexSnippet(_apiUrl, model = DEFAULT_MODEL) {
  return `// After Cloudiator Setup (protected custom setting) or Named Credential callout:Cloudiator
// Http layer uses setTimeout(120000) and Salesforce keys force stream: false.
CloudiatorService.Result r = CloudiatorService.chat(
  prompt,
  '${model}',
  512,
  null // related record Id optional
);
System.debug(r.requestId + ' => ' + r.text);
// Call log row is inserted automatically (Cloudiator_Call_Log__c).
`;
}

export function apexNamedCredentialSnippet(model = DEFAULT_MODEL) {
  return `HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Cloudiator/v1/chat/completions');
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setTimeout(120000);
req.setBody(JSON.serialize(new Map<String, Object>{
  'model' => '${model}',
  'stream' => false,
  'max_tokens' => 512,
  'messages' => new List<Object>{
    new Map<String, Object>{ 'role' => 'user', 'content' => prompt }
  }
}));
HttpResponse res = new Http().send(req);
`;
}

export function jsonBodyExample(model = DEFAULT_MODEL) {
  return JSON.stringify(
    {
      model,
      stream: false,
      max_tokens: 512,
      messages: [{ role: "user", content: "hi" }],
    },
    null,
    2,
  );
}

export function openApiCurl(apiUrl, keyPlaceholder = "sk-cld-…") {
  return `curl -sS '${apiUrl}/v1/openapi.json?target=salesforce' \\
  -H 'Authorization: Bearer ${keyPlaceholder}' \\
  -o cloudiator-salesforce.openapi.json`;
}
