import { useEffect, useState } from "react";
import { haptic } from "./haptic.js";

function referenceList(bundle) {
  if (Array.isArray(bundle?.references) && bundle.references.length) return bundle.references;
  return [];
}

function answerBody(text) {
  const marker = "\n\nReferences\n";
  const at = text.indexOf(marker);
  return at === -1 ? text : text.slice(0, at);
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
          When Research is on, the Mini reads Wikipedia, DuckDuckGo, Reddit, Google News, Open-Meteo, and Open
          Library, then writes the answer with [1] citations and a reference list. The key needs{" "}
          <code>tools.research</code>.
        </p>
        <button type="submit" className="btn btn-primary" disabled={busy || !key.trim()}>
          {busy ? "Waiting on the Mini…" : "Send"}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {reply ? (
        <div className="reply" dir="auto">
          {answerBody(reply)}
        </div>
      ) : null}
      {inputs && referenceList(inputs).length ? (
        <div className="research-hits">
          <p className="muted">References</p>
          {referenceList(inputs).map((ref) => (
            <article key={`${ref.n}-${ref.url}`} className="research-hit">
              <div className="src">
                [{ref.n}] {ref.source}
              </div>
              {ref.url ? (
                <a href={ref.url} target="_blank" rel="noreferrer">
                  {ref.title}
                </a>
              ) : (
                <strong>{ref.title}</strong>
              )}
            </article>
          ))}
          {(inputs.notes || []).map((note) => (
            <p key={`${note.source}-${note.message}`} className="research-note">
              {note.source}: {note.message}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
