export const DEFAULT_MODEL = "gemma4:e4b-it-qat";

export function namedCredentialSteps(apiUrl) {
  return [
    "Setup → Named Credentials → External Credentials → New, protocol Custom.",
    "Add a Principal (e.g. CloudiatorPrincipal). On the principal, add parameter ApiKey = the sk-cld- key shown once above.",
    "Add a Custom Header: Authorization = Bearer {!$Credential.CloudiatorPrincipal.ApiKey}. Never hardcode the key in Apex.",
    `Setup → Named Credentials → New, URL ${apiUrl} (no trailing slash), linked to that External Credential. Enable "Allow formulas in HTTP header".`,
    "Create a permission set that grants the running user the External Credential Principal, and assign it. Without this step the callout 401s while curl works.",
    "Remote Site Settings are not needed when using Named Credentials.",
  ];
}

export function apexSnippet(apiUrl, model = DEFAULT_MODEL) {
  return `// Named Credential URL is ${apiUrl} (no trailing slash).
// Salesforce keys force "stream": false. Apex default timeout is 10s.
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
