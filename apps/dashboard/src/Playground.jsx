import { useEffect, useState } from "react";
import { haptic } from "./haptic.js";
import {
  EMBED_MODEL,
  SERVICES,
  buildRequest,
  describeRequest,
  serviceById,
  summarize,
} from "./playgroundServices.js";

export function Playground({ apiUrl, model, initialKey, keyScopes }) {
  const [key, setKey] = useState(initialKey || "");
  const [serviceId, setServiceId] = useState("chat");
  const [fields, setFields] = useState(() => ({
    model: model || "gemma4:e4b-it-qat",
    system: "",
    prompt: "اكتب جملة واحدة بالفصحى عن الطقس.",
    maxTokens: "512",
    temperature: "",
    jsonObject: false,
    embedModel: EMBED_MODEL,
    embedInput: "الطقس اليوم مشمس في القاهرة.",
    openapiTarget: "",
    customMethod: "GET",
    customPath: "/v1/models",
    customBody: '{\n  "model": "gemma4:e4b-it-qat",\n  "stream": false,\n  "messages": [{ "role": "user", "content": "hi" }]\n}',
  }));
  const [rawOn, setRawOn] = useState(false);
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (initialKey) setKey(initialKey);
  }, [initialKey]);

  useEffect(() => {
    if (model) {
      setFields((current) => (current.model ? current : { ...current, model }));
    }
  }, [model]);

  const service = serviceById(serviceId);
  const preview = describeRequest(serviceId, fields);
  const canRaw = serviceId === "chat" || serviceId === "embeddings";
  let requiresKey = service.requiresKey;
  try {
    requiresKey = buildRequest(serviceId, fields, { rawBody: rawOn && canRaw ? rawText : null }).requiresKey;
  } catch {
    /* An incomplete form still follows the service default. */
  }
  const scopes = Array.isArray(keyScopes) ? keyScopes : [];
  const missingScope = service.scope && scopes.length > 0 && !scopes.includes(service.scope);

  function patch(name, value) {
    setFields((current) => ({ ...current, [name]: value }));
  }

  function seedRaw() {
    try {
      const built = buildRequest(serviceId, fields);
      setRawText(JSON.stringify(built.body, null, 2));
    } catch {
      setRawText((current) => current || "{\n}\n");
    }
  }

  function choose(next) {
    haptic("select");
    setServiceId(next);
    setRawOn(false);
    setError("");
    setResult(null);
  }

  async function send(event) {
    event.preventDefault();
    haptic("tap");
    setBusy(true);
    setError("");
    setResult(null);
    let built;
    try {
      built = buildRequest(serviceId, fields, { rawBody: rawOn && canRaw ? rawText : null });
    } catch (err) {
      setError(err.message);
      setBusy(false);
      haptic("warn");
      return;
    }
    if (built.requiresKey && !key.trim()) {
      setError("API key is required for this call.");
      setBusy(false);
      haptic("warn");
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), built.timeoutMs);
    try {
      const headers = {};
      if (key.trim()) headers.Authorization = `Bearer ${key.trim()}`;
      if (built.body) headers["Content-Type"] = "application/json";
      const response = await fetch(`${apiUrl}${built.path}`, {
        method: built.method,
        signal: controller.signal,
        headers,
        body: built.body ? JSON.stringify(built.body) : undefined,
      });
      const raw = await response.text();
      let body = null;
      try {
        body = raw ? JSON.parse(raw) : null;
      } catch {
        body = null;
      }
      if (!response.ok) {
        throw new Error(body?.error?.message || raw.slice(0, 400) || `Request failed (${response.status})`);
      }
      const view = body ? summarize(serviceId, body) : { lead: raw, jsonText: raw };
      setResult({
        status: response.status,
        requestId: response.headers.get("x-request-id") || "",
        lead: view.lead,
        jsonText: view.jsonText,
      });
      haptic("success");
    } catch (err) {
      setError(err.name === "AbortError" ? `Timed out at ${built.timeoutMs / 1000}s.` : err.message);
      haptic("warn");
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  const action = serviceId === "chat" ? "Send" : serviceId === "embeddings" ? "Embed" : "Run";

  return (
    <section className={busy ? "card glass playground is-busy" : "card glass playground"}>
      <h2>Playground</h2>
      <p className="muted">
        Calls <code>{apiUrl}</code> from this browser with the minted key. Pick a service, or use Custom for any{" "}
        <code>/v1</code> route. Netlify never runs inference.
      </p>
      <form className="stack" onSubmit={send}>
        <label>
          API key
          <input
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="sk-cld-…"
            autoComplete="off"
            required={requiresKey}
          />
        </label>
        <div className="service-picks" role="radiogroup" aria-label="Service">
          {SERVICES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={item.id === serviceId}
              className={item.id === serviceId ? "on" : ""}
              onClick={() => choose(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <p className="playground-meta">
          <span className="pill">{preview.method}</span>
          <code>
            {apiUrl}
            {preview.path}
          </code>
        </p>
        <p className="muted">{service.blurb}</p>
        {missingScope ? (
          <p className="error">The selected key does not include {service.scope}. The API will reject the call.</p>
        ) : null}

        {serviceId === "chat" ? (
          <>
            <label>
              Model
              <input value={fields.model} onChange={(event) => patch("model", event.target.value)} required={!rawOn} />
            </label>
            <label>
              System
              <textarea
                dir="auto"
                rows={2}
                value={fields.system}
                placeholder="Optional system prompt"
                onChange={(event) => patch("system", event.target.value)}
              />
            </label>
            <label>
              Message
              <textarea
                dir="auto"
                rows={6}
                value={fields.prompt}
                onChange={(event) => patch("prompt", event.target.value)}
                required={!rawOn}
              />
            </label>
            <div className="pair">
              <label>
                Max tokens
                <input
                  inputMode="numeric"
                  value={fields.maxTokens}
                  onChange={(event) => patch("maxTokens", event.target.value)}
                  required={!rawOn}
                />
              </label>
              <label>
                Temperature
                <input
                  inputMode="decimal"
                  value={fields.temperature}
                  placeholder="model default"
                  onChange={(event) => patch("temperature", event.target.value)}
                />
              </label>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={fields.jsonObject}
                onChange={(event) => patch("jsonObject", event.target.checked)}
              />
              JSON object response
            </label>
          </>
        ) : null}

        {serviceId === "embeddings" ? (
          <>
            <label>
              Model
              <input
                value={fields.embedModel}
                onChange={(event) => patch("embedModel", event.target.value)}
                required={!rawOn}
              />
            </label>
            <label>
              Input
              <textarea
                dir="auto"
                rows={6}
                value={fields.embedInput}
                onChange={(event) => patch("embedInput", event.target.value)}
                required={!rawOn}
              />
            </label>
          </>
        ) : null}

        {serviceId === "openapi" ? (
          <label>
            Target
            <select value={fields.openapiTarget} onChange={(event) => patch("openapiTarget", event.target.value)}>
              <option value="">This key</option>
              <option value="salesforce">Salesforce (External Services)</option>
            </select>
          </label>
        ) : null}

        {serviceId === "custom" ? (
          <>
            <div className="pair">
              <label>
                Method
                <select value={fields.customMethod} onChange={(event) => patch("customMethod", event.target.value)}>
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                </select>
              </label>
              <label>
                Path
                <input
                  value={fields.customPath}
                  onChange={(event) => patch("customPath", event.target.value)}
                  placeholder="/v1/…"
                  required
                />
              </label>
            </div>
            {fields.customMethod === "POST" ? (
              <label>
                Body
                <textarea
                  rows={8}
                  spellCheck={false}
                  value={fields.customBody}
                  onChange={(event) => patch("customBody", event.target.value)}
                />
              </label>
            ) : null}
          </>
        ) : null}

        {canRaw ? (
          <div className="stack">
            <label className="check">
              <input
                type="checkbox"
                checked={rawOn}
                onChange={(event) => {
                  if (event.target.checked) seedRaw();
                  setRawOn(event.target.checked);
                }}
              />
              Send raw JSON
            </label>
            {rawOn ? (
              <>
                <label>
                  Request body
                  <textarea
                    rows={10}
                    spellCheck={false}
                    value={rawText}
                    onChange={(event) => setRawText(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    haptic("select");
                    seedRaw();
                  }}
                >
                  Reset raw JSON from the fields
                </button>
              </>
            ) : null}
          </div>
        ) : null}

        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Waiting on the Mini…" : action}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {result ? (
        <div className="stack">
          <p className="muted">
            {result.status}
            {result.requestId ? ` · ${result.requestId}` : ""}
          </p>
          {result.lead ? (
            <div className="reply" dir="auto">
              {result.lead}
            </div>
          ) : null}
          {result.jsonText ? <pre className="reply">{result.jsonText}</pre> : null}
        </div>
      ) : null}
    </section>
  );
}
