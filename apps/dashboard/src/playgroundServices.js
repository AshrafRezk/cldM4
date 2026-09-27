/** Browser calls the Mini's public API. Netlify never runs inference. */

export const EMBED_MODEL = "nomic-embed-text";

export const SERVICES = [
  {
    id: "chat",
    label: "Chat",
    method: "POST",
    path: "/v1/chat/completions",
    scope: "chat",
    requiresKey: true,
    timeoutMs: 90_000,
    blurb:
      "Completions on the chat model. Stream stays off. Raw JSON can add tools, extra turns, stop, or seed.",
  },
  {
    id: "embeddings",
    label: "Embeddings",
    method: "POST",
    path: "/v1/embeddings",
    scope: "embeddings",
    requiresKey: true,
    timeoutMs: 45_000,
    blurb: "One line is a single string. More than one line is sent as an array.",
  },
  {
    id: "models",
    label: "Models",
    method: "GET",
    path: "/v1/models",
    scope: null,
    requiresKey: true,
    timeoutMs: 20_000,
    blurb: "Lists the models this key is allowed to call.",
  },
  {
    id: "usage",
    label: "Usage",
    method: "GET",
    path: "/v1/usage",
    scope: null,
    requiresKey: true,
    timeoutMs: 20_000,
    blurb: "Daily rollup for this key.",
  },
  {
    id: "events",
    label: "Events",
    method: "GET",
    path: "/v1/usage/events",
    scope: null,
    requiresKey: true,
    timeoutMs: 20_000,
    blurb: "Recent usage events for this key.",
  },
  {
    id: "openapi",
    label: "OpenAPI",
    method: "GET",
    path: "/v1/openapi.json",
    scope: null,
    requiresKey: true,
    timeoutMs: 20_000,
    blurb: "The contract for this key. Salesforce is the External Services subset.",
  },
  {
    id: "health",
    label: "Health",
    method: "GET",
    path: "/v1/health",
    scope: null,
    requiresKey: false,
    timeoutMs: 15_000,
    blurb: "Appliance status. A key is optional. This call does not round-trip the database.",
  },
  {
    id: "custom",
    label: "Custom",
    method: "GET",
    path: "/v1/models",
    scope: null,
    requiresKey: true,
    timeoutMs: 90_000,
    blurb: "Any GET or POST under /v1 on this API.",
  },
];

const PATH_RE = /^\/v1\/[A-Za-z0-9._~/{}\-]*(\?[A-Za-z0-9._~&=%\-]*)?$/;

export function serviceById(serviceId) {
  const service = SERVICES.find((item) => item.id === serviceId);
  if (!service) throw new Error("Unknown service.");
  return service;
}

export function assertApiPath(path) {
  if (typeof path !== "string" || !PATH_RE.test(path) || path.includes("..") || path.includes("//")) {
    throw new Error("Path must be a /v1/ route on this API.");
  }
  return path;
}

export function parseJsonObject(text, label = "JSON") {
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value;
}

function chatBody(fields) {
  const model = String(fields.model || "").trim();
  if (!model) throw new Error("Model is required.");
  const prompt = String(fields.prompt ?? "");
  if (!prompt.trim()) throw new Error("Message is required.");
  const messages = [];
  const system = String(fields.system || "").trim();
  if (system) messages.push({ role: "system", content: system });
  messages.push({ role: "user", content: prompt });
  const maxTokens = Number(fields.maxTokens);
  if (!Number.isInteger(maxTokens) || maxTokens < 1) {
    throw new Error("Max tokens must be a positive integer.");
  }
  const body = { model, stream: false, max_tokens: maxTokens, messages };
  const temperature = String(fields.temperature ?? "").trim();
  if (temperature !== "") {
    const value = Number(temperature);
    if (!Number.isFinite(value)) throw new Error("Temperature must be a number.");
    body.temperature = value;
  }
  if (fields.jsonObject) body.response_format = { type: "json_object" };
  return body;
}

function embedBody(fields) {
  const model = String(fields.embedModel || "").trim();
  if (!model) throw new Error("Model is required.");
  const lines = String(fields.embedInput || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) throw new Error("Input is required.");
  return { model, input: lines.length === 1 ? lines[0] : lines };
}

function openapiPath(fields) {
  const target = String(fields.openapiTarget || "");
  if (!target) return "/v1/openapi.json";
  if (target !== "salesforce") throw new Error("Unknown OpenAPI target.");
  return "/v1/openapi.json?target=salesforce";
}

function customRequest(fields) {
  const method = fields.customMethod === "POST" ? "POST" : fields.customMethod === "GET" ? "GET" : "";
  if (!method) throw new Error("Method must be GET or POST.");
  const path = assertApiPath(String(fields.customPath || "").trim());
  const body = method === "POST" ? parseJsonObject(fields.customBody, "Request body") : null;
  const bare = path.split("?")[0];
  return {
    method,
    path,
    body,
    requiresKey: !(method === "GET" && bare === "/v1/health"),
    timeoutMs: method === "POST" ? 90_000 : 20_000,
    scope: null,
  };
}

export function describeRequest(serviceId, fields) {
  const service = serviceById(serviceId);
  if (serviceId === "openapi") {
    const target = String(fields.openapiTarget || "");
    return {
      method: "GET",
      path: target === "salesforce" ? "/v1/openapi.json?target=salesforce" : "/v1/openapi.json",
    };
  }
  if (serviceId === "custom") {
    return {
      method: fields.customMethod === "POST" ? "POST" : "GET",
      path: String(fields.customPath || "").trim() || "/v1/",
    };
  }
  return { method: service.method, path: service.path };
}

/**
 * @param {string} serviceId
 * @param {object} fields
 * @param {{ rawBody?: string | null }} [options] When rawBody is a string, POST services send that object.
 */
export function buildRequest(serviceId, fields, options = {}) {
  const service = serviceById(serviceId);
  const rawBody = options.rawBody;
  if ((serviceId === "chat" || serviceId === "embeddings") && typeof rawBody === "string") {
    return {
      method: service.method,
      path: service.path,
      body: parseJsonObject(rawBody, "Request body"),
      requiresKey: service.requiresKey,
      timeoutMs: service.timeoutMs,
      scope: service.scope,
    };
  }
  if (serviceId === "chat") {
    return { ...meta(service), body: chatBody(fields) };
  }
  if (serviceId === "embeddings") {
    return { ...meta(service), body: embedBody(fields) };
  }
  if (serviceId === "openapi") {
    return { ...meta(service), path: openapiPath(fields), body: null };
  }
  if (serviceId === "custom") return customRequest(fields);
  return { ...meta(service), body: null };
}

function meta(service) {
  return {
    method: service.method,
    path: service.path,
    requiresKey: service.requiresKey,
    timeoutMs: service.timeoutMs,
    scope: service.scope,
  };
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

export function summarize(serviceId, body) {
  if (!body || typeof body !== "object") {
    return { lead: "", jsonText: body == null ? "" : String(body) };
  }
  if (serviceId === "chat" || serviceId === "custom") {
    const message = body?.choices?.[0]?.message;
    if (message) {
      const calls = message.tool_calls;
      const lead = message.content || (calls ? pretty(calls) : "");
      return { lead, jsonText: pretty(body) };
    }
  }
  if (serviceId === "embeddings") {
    const data = Array.isArray(body.data) ? body.data : [];
    const lead = data
      .map((item) => {
        const dims = Array.isArray(item.embedding) ? item.embedding.length : 0;
        const preview = Array.isArray(item.embedding)
          ? item.embedding
              .slice(0, 6)
              .map((n) => Number(n).toFixed(4))
              .join(", ")
          : "";
        return `#${item.index} · ${dims} dimensions · ${preview}…`;
      })
      .join("\n");
    const clipped = {
      ...body,
      data: data.map((item) => ({
        object: item.object,
        index: item.index,
        embedding: Array.isArray(item.embedding)
          ? { dimensions: item.embedding.length, preview: item.embedding.slice(0, 8) }
          : item.embedding,
      })),
    };
    return { lead, jsonText: pretty(clipped) };
  }
  if (serviceId === "models" && Array.isArray(body.data)) {
    return { lead: body.data.map((item) => item.id).filter(Boolean).join("\n"), jsonText: pretty(body) };
  }
  return { lead: "", jsonText: pretty(body) };
}
