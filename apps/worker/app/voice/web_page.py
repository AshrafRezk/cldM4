"""The browser call page. One self-contained HTML document, no CDN.

Turn-based on purpose, like the engine: play the prompt, listen until the
caller stops talking, upload one 16 kHz mono WAV, play the next prompt.
"""

from __future__ import annotations

from html import escape

_PAGE = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--accent:#1f6f5c;--danger:#b3261e;--you:#eef4f2}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecece8;--muted:#9a9a93;--line:#30302d;--accent:#5fbfa5;--danger:#f2b8b5;--you:#1f2b28}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,sans-serif}
main{max-width:560px;margin:0 auto;padding:24px 16px}
h1{font-size:20px;margin:0 0 4px}
p.sub{color:var(--muted);margin:0 0 20px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
#log{display:flex;flex-direction:column;gap:8px;min-height:120px;max-height:55vh;overflow-y:auto;margin-bottom:16px}
.line{padding:8px 12px;border-radius:10px;max-width:90%;unicode-bidi:plaintext}
.agent{align-self:flex-start;border:1px solid var(--line)}
.you{align-self:flex-end;background:var(--you)}
.row{display:flex;gap:12px;align-items:center}
button{font:inherit;border:0;border-radius:999px;padding:12px 22px;cursor:pointer}
#call{background:var(--accent);color:#fff}
#hang{background:transparent;color:var(--danger);border:1px solid var(--line);display:none}
#status{color:var(--muted);font-size:14px;flex:1}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--danger);margin-inline-end:6px;animation:p 1s infinite}
@keyframes p{50%{opacity:.3}}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<p class="sub">Voice call in your browser. Allow the microphone when asked.</p>
<div class="card">
  <div id="log" aria-live="polite"></div>
  <div class="row">
    <button id="call">Call</button>
    <button id="hang">Hang up</button>
    <span id="status"></span>
  </div>
</div>
</main>
<script>
(() => {
  const base = location.pathname.replace(/\\/$/, "");
  const $ = (id) => document.getElementById(id);
  const logEl = $("log"), statusEl = $("status"), callBtn = $("call"), hangBtn = $("hang");
  let ctx = null, stream = null, source = null, live = false;

  const say = (who, text) => {
    const div = document.createElement("div");
    div.className = "line " + who; div.dir = "auto"; div.textContent = text;
    logEl.appendChild(div); logEl.scrollTop = logEl.scrollHeight;
  };
  const status = (html) => { statusEl.innerHTML = html; };

  async function post(path, body) {
    const res = await fetch(base + path, {
      method: "POST", body: body || null,
      headers: body ? { "Content-Type": "audio/wav" } : {},
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data.error && data.error.message) || ("HTTP " + res.status));
    return data;
  }

  async function play(dataUrl) {
    const buf = await (await fetch(dataUrl)).arrayBuffer();
    const audio = await ctx.decodeAudioData(buf);
    await new Promise((resolve) => {
      const node = ctx.createBufferSource();
      node.buffer = audio; node.connect(ctx.destination); node.onended = resolve; node.start();
    });
  }

  // Record one answer: wait up to `timeout` s for speech, stop after a pause.
  function listen(spec) {
    return new Promise((resolve) => {
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = []; const started = performance.now();
      const pauseMs = spec.speech_timeout === "auto" ? 1200 : Math.max(500, Number(spec.speech_timeout) * 1000 || 1200);
      let noise = 0, frames = 0, speaking = false, lastVoice = 0;
      proc.onaudioprocess = (e) => {
        if (!live) { finish(false); return; }
        const data = e.inputBuffer.getChannelData(0);
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length); const now = performance.now();
        if (frames < 4) { noise = Math.max(noise, rms); frames++; return; }
        const threshold = Math.max(0.015, noise * 3);
        if (rms > threshold) { speaking = true; lastVoice = now; }
        if (speaking) chunks.push(new Float32Array(data));
        if (speaking && now - lastVoice > pauseMs) finish(true);
        else if (!speaking && now - started > spec.timeout * 1000) finish(false);
        else if (now - started > 25000) finish(speaking);
      };
      let done = false;
      function finish(heard) {
        if (done) return; done = true;
        proc.disconnect(); source.disconnect(proc);
        resolve(heard ? wav(chunks, ctx.sampleRate) : new Blob([]));
      }
      source.connect(proc); proc.connect(ctx.destination);
      status('<span class="dot"></span>Listening…');
    });
  }

  function wav(chunks, rate) {
    const len = chunks.reduce((n, c) => n + c.length, 0);
    const ratio = rate / 16000, outLen = Math.floor(len / ratio);
    const all = new Float32Array(len); let o = 0;
    for (const c of chunks) { all.set(c, o); o += c.length; }
    const buf = new ArrayBuffer(44 + outLen * 2), v = new DataView(buf);
    const str = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + outLen * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, outLen * 2, true);
    for (let i = 0; i < outLen; i++) {
      const s = Math.max(-1, Math.min(1, all[Math.floor(i * ratio)]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function handle(t) {
    while (live) {
      if (t.heard) say("you", t.heard);
      for (const clip of t.clips) {
        say("agent", clip.text);
        if (clip.audio && live) { status("Speaking…"); await play(clip.audio); }
      }
      if (t.done || !t.listen || !live) break;
      const audio = await listen(t.listen);
      if (!live) break;
      status("Thinking…");
      const q = new URLSearchParams({ call_id: t.call_id, step: t.listen.step, attempt: t.listen.attempt });
      t = await post("/turn?" + q, audio);
    }
    end(live ? "Call ended. Thank you." : "You hung up.");
  }

  function end(message) {
    live = false;
    if (stream) stream.getTracks().forEach((tr) => tr.stop());
    callBtn.style.display = ""; hangBtn.style.display = "none"; callBtn.disabled = false;
    status(message);
  }

  callBtn.onclick = async () => {
    callBtn.disabled = true; status("Connecting…");
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      source = ctx.createMediaStreamSource(stream);
      live = true; logEl.textContent = "";
      callBtn.style.display = "none"; hangBtn.style.display = "";
      await handle(await post("/start"));
    } catch (err) {
      end("Call failed: " + err.message);
    }
  };
  hangBtn.onclick = () => end("You hung up.");
})();
</script>
</body>
</html>
"""


def render_page(*, title: str, language: str | None) -> str:
    lang = escape((language or "en").split("-")[0], quote=True)
    return _PAGE.replace("__TITLE__", escape(title)).replace("__LANG__", lang)
