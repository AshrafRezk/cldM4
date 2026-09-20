import { useEffect, useState } from "react";

export function Playground({ apiUrl, model, initialKey }) {
  const [key, setKey] = useState(initialKey || "");
  const [prompt, setPrompt] = useState("اكتب جملة واحدة بالفصحى عن الطقس.");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialKey) setKey(initialKey);
  }, [initialKey]);

  async function send(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setReply("");
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
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.error?.message || `Chat failed (${response.status})`);
      }
      const text = body?.choices?.[0]?.message?.content || JSON.stringify(body);
      setReply(text);
    } catch (err) {
      setError(err.name === "AbortError" ? "Timed out at 90s (worker deadline)." : err.message);
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  return (
    <section className="card">
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
        <button type="submit" disabled={busy || !key.trim()}>
          {busy ? "Waiting on the Mini…" : "Send"}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {reply ? (
        <div className="reply" dir="auto">
          {reply}
        </div>
      ) : null}
    </section>
  );
}
