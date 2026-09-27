import { useEffect, useState } from "react";
import { haptic } from "./haptic.js";

const RESEARCH_KEYS = ["web", "reddit", "news", "books"];

function researchLines(bundle) {
  if (!bundle) return [];
  const lines = [];
  for (const key of RESEARCH_KEYS) {
    for (const hit of bundle[key] || []) {
      lines.push({
        source: hit.source || key,
        title: hit.title || hit.snippet || key,
        snippet: hit.snippet || "",
        url: hit.url || "",
      });
    }
  }
  const weather = bundle.weather;
  if (weather?.found) {
    const temp = weather.temperature_c == null ? "" : `${weather.temperature_c}°C `;
    lines.push({
      source: "weather",
      title: weather.place || "Weather",
      snippet: `${temp}${weather.summary || ""}`.trim(),
      url: "",
    });
  }
  return lines;
}

export function Playground({ apiUrl, model, initialKey }) {
  const [key, setKey] = useState(initialKey || "");
  const [prompt, setPrompt] = useState("اكتب جملة واحدة بالفصحى عن الطقس.");
  const [research, setResearch] = useState(true);
  const [reply, setReply] = useState("");
  const [inputs, setInputs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialKey) setKey(initialKey);
  }, [initialKey]);

  async function send(event) {
    event.preventDefault();
    haptic("tap");
    setBusy(true);
    setError("");
    setReply("");
    setInputs(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(`${apiUrl}/v1/chat/completions`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${key.trim()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model,
          stream: false,
          max_tokens: 512,
          messages: [{ role: "user", content: prompt }],
          ...(research ? { research: true } : {}),
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.error?.message || `Chat failed (${response.status})`);
      }
      const text = body?.choices?.[0]?.message?.content || JSON.stringify(body);
      setReply(text);
      setInputs(body?.research || null);
      haptic("success");
    } catch (err) {
      setError(err.name === "AbortError" ? "Timed out at 90s (worker deadline)." : err.message);
      haptic("warn");
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  return (
    <section className={busy ? "card glass playground is-busy" : "card glass playground"}>
      <h2>Playground</h2>
      <p className="muted">
        Calls <code>{apiUrl}/v1/chat/completions</code> from this browser with the minted key. Netlify never runs
        inference.
      </p>
      <form className="stack" onSubmit={send}>
        <label>
          API key
          <input
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="sk-cld-…"
            autoComplete="off"
            required
          />
        </label>
        <label>
          Message
          <textarea dir="auto" rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={research}
            onChange={(event) => {
              haptic("select");
              setResearch(event.target.checked);
            }}
          />
          Research
        </label>
        <p className="muted">
          When Research is on, the Mini looks up the prompt on Wikipedia, DuckDuckGo, Reddit, Google News,
          Open-Meteo, and Open Library, then returns those inputs with the answer. The key needs{" "}
          <code>tools.research</code>.
        </p>
        <button type="submit" className="btn btn-primary" disabled={busy || !key.trim()}>
          {busy ? "Waiting on the Mini…" : "Send"}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {inputs ? (
        <div className="research-hits">
          <p className="muted">Inputs for &quot;{inputs.query}&quot;</p>
          {researchLines(inputs).map((hit) => (
            <article key={`${hit.source}-${hit.title}-${hit.url}`} className="research-hit">
              <div className="src">{hit.source}</div>
              {hit.url ? (
                <a href={hit.url} target="_blank" rel="noreferrer">
                  {hit.title}
                </a>
              ) : (
                <strong>{hit.title}</strong>
              )}
              {hit.snippet ? <p>{hit.snippet}</p> : null}
            </article>
          ))}
          {(inputs.notes || []).map((note) => (
            <p key={`${note.source}-${note.message}`} className="research-note">
              {note.source}: {note.message}
            </p>
          ))}
          {researchLines(inputs).length === 0 && !(inputs.notes || []).length ? (
            <p className="muted">No public hits for this prompt.</p>
          ) : null}
        </div>
      ) : null}
      {reply ? (
        <div className="reply" dir="auto">
          {reply}
        </div>
      ) : null}
    </section>
  );
}
