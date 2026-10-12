/** Salesforce guide payloads for GET /api/salesforce-snippet. Keep in sync with src/salesforceSnippets.js. */

export const DEFAULT_MODEL = "gemma4:e4b-it-qat";

export const SERVICES = [
  { id: "chat", name: "Chat", path: "POST /v1/chat/completions", flow: "Cloudiator: Chat", modality: "Text → Text" },
  { id: "embeddings", name: "Embeddings", path: "POST /v1/embeddings", flow: "Cloudiator: Embeddings", modality: "Text → Binary" },
  { id: "ocr", name: "OCR", path: "POST /v1/tools/ocr", flow: "Cloudiator: OCR", modality: "Image → Text" },
  { id: "geocode", name: "Geocode", path: "POST /v1/tools/geocode", flow: "Cloudiator: Geocode", modality: "Text → Text" },
  { id: "research", name: "Research", path: "POST /v1/tools/research", flow: "Cloudiator: Research", modality: "Text → Text" },
  { id: "chart", name: "Chart", path: "POST /v1/tools/chart", flow: "Cloudiator: Chart", modality: "Text → Image" },
  { id: "stats", name: "Stats", path: "POST /v1/tools/stats", flow: "Cloudiator: Stats", modality: "Text → Text" },
  { id: "query", name: "Query", path: "POST /v1/tools/query", flow: "Cloudiator: Query", modality: "Text → Text" },
  { id: "document", name: "Document", path: "POST /v1/tools/document", flow: "Cloudiator: Document", modality: "Binary → Mixed" },
  { id: "text", name: "Text tools", path: "POST /v1/tools/text", flow: "Cloudiator: Text tools", modality: "Text → Text" },
  { id: "time", name: "Time", path: "POST /v1/tools/time", flow: "Cloudiator: Time", modality: "Text → Text" },
  { id: "image_ops", name: "Image ops", path: "POST /v1/tools/image", flow: "Cloudiator: Image ops", modality: "Image → Image" },
  {
    id: "jobs",
    name: "Image job (FLUX)",
    path: "POST /v1/jobs",
    flow: "Cloudiator: Create image job",
    modality: "Text → Image (async)",
    note: "Needs image_generation scope",
  },
  {
    id: "audio",
    name: "Audio",
    path: "—",
    flow: "—",
    modality: "Audio → Text (later)",
    note: "Not in v1 engineer OpenAPI",
  },
];

export function namedCredentialSteps(apiUrl) {
  return [
    "Setup → Named Credentials → External Credentials → New, protocol Custom.",
    "Add a Principal (e.g. CloudiatorPrincipal). On the principal, add parameter ApiKey = the sk-cld- key shown once above.",
    "Add a Custom Header: Authorization = Bearer {!$Credential.CloudiatorPrincipal.ApiKey}. Never hardcode the key in Apex.",
    `Setup → Named Credentials → New, name Cloudiator, URL ${apiUrl} (no trailing slash), linked to that External Credential. Enable "Allow formulas in HTTP header".`,
    "Create a permission set that grants the running user the External Credential Principal, and assign it. Without this step the callout 401s while curl works.",
    "Optional: deploy salesforce/ unmanaged app and enable Use Named Credential in Cloudiator Setup.",
  ];
}

export function installSteps() {
  return [
    "Mint a Salesforce engineer key, or paste an existing sk-cld-… from your password manager.",
    "Console → Salesforce → Install & connect, or Connect existing key only if the org already has the app.",
    "Fallback: deploy salesforce/force-app (sf project deploy) or Workbench zip; assign Cloudiator Admin.",
    "App Launcher → Cloudiator → Setup → confirm key → Test /v1/health.",
    "Use Cloudiator:* Flow actions; inspect Cloudiator Call Logs.",
  ];
}

export function apexSnippet(apiUrl, model = DEFAULT_MODEL) {
  return `// Named Credential URL is ${apiUrl} (no trailing slash).
// Salesforce keys force stream: false. Apex default timeout is 10s.
HttpRequest req = new HttpRequest();
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

export function packageApexSnippet(model = DEFAULT_MODEL) {
  return `CloudiatorService.Result r = CloudiatorService.chat(prompt, '${model}', 512, null);
System.debug(r.requestId + ' => ' + r.text);
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
