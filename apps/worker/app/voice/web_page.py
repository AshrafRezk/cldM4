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
.call{background:var(--accent);color:#fff}
.who{margin:0 0 14px}
.who p{margin:0 0 8px;color:var(--muted);font-size:14px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--line);border-radius:999px;padding:6px 14px;cursor:pointer;font-size:15px}
.chip input{position:absolute;opacity:0;pointer-events:none}
.chip:has(input:checked){border-color:var(--accent);background:var(--you);font-weight:600}
.row{flex-wrap:wrap}
#hang{background:transparent;color:var(--danger);border:1px solid var(--line);display:none}
#status{color:var(--muted);font-size:14px;flex:1}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--danger);margin-inline-end:6px;animation:p 1s infinite}
@keyframes p{50%{opacity:.3}}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<p class="sub">Choose a language, then allow the microphone. <span dir="rtl">اختار اللغة، وبعدين اسمح باستخدام المايك.</span></p>
<div class="card">
  __PERSONAS__
  <div id="log" aria-live="polite"></div>
  <div class="row">
    __BUTTONS__
    <button id="hang">Hang up</button>
    <span id="status"></span>
  </div>
</div>
</main>
<script>
(() => {
  const base = location.pathname.replace(/\\/$/, "");
  const $ = (id) => document.getElementById(id);
  const logEl = $("log"), statusEl = $("status"), hangBtn = $("hang");
  const callBtns = [...document.querySelectorAll(".call")];
  const TEXT = {
    ar: { listening: "بسمعك…", speaking: "بيتكلم…", thinking: "لحظة واحدة…", connecting: "بنوصّلك…",
          ended: "المكالمة خلصت. شكراً ليك.", hung: "إنت قفلت المكالمة.", failed: "المكالمة ما اشتغلتش: ", hang: "إنهاء المكالمة",
          queued: (n) => "كل الخطوط مشغولة. إنت رقم " + n + " في الدور، خليك معانا." },
    en: { listening: "Listening…", speaking: "Speaking…", thinking: "One moment…", connecting: "Connecting…",
          ended: "Call ended. Thank you.", hung: "You hung up.", failed: "Call failed: ", hang: "Hang up",
          queued: (n) => "All lines are busy. You are number " + n + " in line; please stay with us." },
  };
  let t$ = TEXT.en;
  let ctx = null, stream = null, source = null, live = false;
  let callId = null, ticket = null;

  // Tell the Mini this caller is gone, even while the page is closing.
  function release() {
    const path = ticket ? "/leave?ticket=" + encodeURIComponent(ticket)
      : callId ? "/hangup?call_id=" + encodeURIComponent(callId) : null;
    ticket = null; callId = null;
    if (path) navigator.sendBeacon(base + path, new Blob([]));
  }
  window.addEventListener("pagehide", release);

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // "Answer after the beep": a short soft tone right before we start listening.
  function beep() {
    const osc = ctx.createOscillator(), gain = ctx.createGain(), now = ctx.currentTime;
    osc.frequency.value = 880; osc.type = "sine";
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.25, now + 0.02);
    gain.gain.setValueAtTime(0.25, now + 0.16);
    gain.gain.linearRampToValueAtTime(0, now + 0.2);
    osc.connect(gain).connect(ctx.destination); osc.start(now); osc.stop(now + 0.22);
    return sleep(260);
  }
  const persona = () => { const c = document.querySelector('input[name="persona"]:checked'); return c ? c.value : null; };

  // Hold music, made here: slow, soft major-seventh chords. No file, no licence,
  // nothing fetched from anyone. `duck` lowers it under the spoken message.
  function holdMusic() {
    const master = ctx.createGain(); master.gain.value = 0.0; master.connect(ctx.destination);
    master.gain.linearRampToValueAtTime(0.05, ctx.currentTime + 2);
    const chords = [[261.63, 329.63, 392.0, 493.88], [220.0, 261.63, 329.63, 392.0],
                    [174.61, 220.0, 261.63, 329.63], [196.0, 246.94, 293.66, 349.23]];
    let i = 0, stopped = false, timer = null;
    function bar() {
      if (stopped) return;
      const now = ctx.currentTime, chord = chords[i++ % chords.length];
      chord.forEach((f, k) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = k === 0 ? "triangle" : "sine"; o.frequency.value = k === 0 ? f / 2 : f;
        g.gain.setValueAtTime(0, now); g.gain.linearRampToValueAtTime(0.22, now + 1.5);
        g.gain.linearRampToValueAtTime(0.0, now + 5.2);
        o.connect(g).connect(master); o.start(now); o.stop(now + 5.3);
      });
      // a gentle note on top every bar
      const n = ctx.createOscillator(), ng = ctx.createGain();
      n.type = "sine"; n.frequency.value = chord[(i % 3) + 1] * 2;
      ng.gain.setValueAtTime(0, now + 1); ng.gain.linearRampToValueAtTime(0.08, now + 1.4);
      ng.gain.linearRampToValueAtTime(0, now + 3.5);
      n.connect(ng).connect(master); n.start(now + 1); n.stop(now + 3.6);
      timer = setTimeout(bar, 4800);
    }
    bar();
    return {
      duck(on) { master.gain.linearRampToValueAtTime(on ? 0.012 : 0.05, ctx.currentTime + 0.4); },
      stop() { stopped = true; clearTimeout(timer); master.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.6); },
    };
  }

  // Queued: show the position, play music, say the hold message now and every
  // 30 s over the music, and ask every few seconds whether it is our turn.
  async function waitInLine(q) {
    ticket = q.ticket;
    const holdClip = q.clips[0];
    const music = q.music ? holdMusic() : null;
    const every = (q.repeat_seconds || 30) * 1000;
    let lastHold = -Infinity;
    if (holdClip) say("agent", holdClip.text);
    try {
      while (live) {
        status(t$.queued(q.position));
        if (holdClip && holdClip.audio && performance.now() - lastHold > every) {
          lastHold = performance.now();
          if (music) music.duck(true);
          play(holdClip.audio).catch(() => {}).finally(() => { if (music) music.duck(false); });
        }
        await sleep((q.poll_seconds || 3) * 1000);
        if (!live) break;
        const next = await post("/wait?ticket=" + encodeURIComponent(ticket));
        if (!next.queued) { ticket = null; return next; }
        q = { ...next, clips: q.clips, music: q.music, repeat_seconds: q.repeat_seconds };
      }
      return null;
    } finally {
      if (music) music.stop();
    }
  }

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
  // Half a second before the detected start is kept, so the first syllable of
  // a short answer (a name) is not cut off. The noise floor follows the room
  // while nobody is talking instead of being guessed from the first frames.
  function listen(spec) {
    return new Promise((resolve) => {
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [], preroll = []; const started = performance.now();
      const prerollChunks = Math.ceil((0.5 * ctx.sampleRate) / 4096);
      const pauseMs = spec.speech_timeout === "auto" ? 1300 : Math.max(500, Number(spec.speech_timeout) * 1000 || 1300);
      let noise = 0.004, speaking = false, lastVoice = 0, voiced = 0;
      proc.onaudioprocess = (e) => {
        if (!live) { finish(false); return; }
        const data = new Float32Array(e.inputBuffer.getChannelData(0));
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length); const now = performance.now();
        const threshold = Math.max(0.01, noise * 3);
        if (!speaking) {
          if (rms > threshold) {
            speaking = true; lastVoice = now; chunks.push(...preroll, data); voiced++;
          } else {
            noise = noise * 0.9 + rms * 0.1;
            preroll.push(data); if (preroll.length > prerollChunks) preroll.shift();
            if (now - started > spec.timeout * 1000) finish(false);
          }
          return;
        }
        chunks.push(data);
        if (rms > threshold) { lastVoice = now; voiced++; }
        if (now - lastVoice > pauseMs) finish(voiced > 1);
        else if (now - started > 30000) finish(true);
      };
      let done = false;
      function finish(heard) {
        if (done) return; done = true;
        proc.disconnect(); source.disconnect(proc);
        resolve(heard ? wav(chunks, ctx.sampleRate) : new Blob([]));
      }
      source.connect(proc); proc.connect(ctx.destination);
      status('<span class="dot"></span>' + t$.listening);
    });
  }

  // 16-bit mono WAV at the microphone's own rate. The Mini resamples with
  // ffmpeg; decimating here without a filter aliases and hurts recognition.
  function wav(chunks, rate) {
    const len = chunks.reduce((n, c) => n + c.length, 0);
    const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
    const str = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, len * 2, true);
    let o = 44;
    for (const c of chunks) {
      for (let i = 0; i < c.length; i++, o += 2) {
        const s = Math.max(-1, Math.min(1, c[i]));
        v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function handle(t) {
    callId = t.call_id;
    while (live) {
      if (t.heard) say("you", t.heard);
      for (const clip of t.clips) {
        say("agent", clip.text);
        if (clip.audio && live) { status(t$.speaking); await play(clip.audio); }
      }
      if (t.done || !t.listen || !live) break;
      if (t.listen.beep !== false) await beep();
      const audio = await listen(t.listen);
      if (!live) break;
      status(t$.thinking);
      const q = new URLSearchParams({ call_id: t.call_id, step: t.listen.step, attempt: t.listen.attempt, turn: t.listen.turn });
      document.querySelectorAll('input[name="persona"]').forEach((i) => { i.disabled = true; });
      t = await post("/turn?" + q, audio);
    }
    if (live) callId = null;  // the Mini already freed the line when the call finished
    end(live ? t$.ended : t$.hung);
  }

  function end(message) {
    release();
    live = false;
    if (stream) stream.getTracks().forEach((tr) => tr.stop());
    callBtns.forEach((b) => { b.style.display = ""; b.disabled = false; }); hangBtn.style.display = "none";
    document.querySelectorAll('input[name="persona"]').forEach((i) => { i.disabled = false; });
    status(message);
  }

  async function call(lang) {
    t$ = TEXT[lang.split("-")[0]] || TEXT.en;
    hangBtn.textContent = t$.hang;
    callBtns.forEach((b) => { b.disabled = true; }); status(t$.connecting);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      source = ctx.createMediaStreamSource(stream);
      live = true; logEl.textContent = "";
      callBtns.forEach((b) => { b.style.display = "none"; }); hangBtn.style.display = "";
      const who = persona();
      let first = await post("/start?lang=" + encodeURIComponent(lang) + (who ? "&persona=" + encodeURIComponent(who) : ""));
      if (first.queued) first = await waitInLine(first);
      if (first) await handle(first);
    } catch (err) {
      end(t$.failed + err.message);
    }
  }
  callBtns.forEach((b) => { b.onclick = () => call(b.dataset.lang); });
  hangBtn.onclick = () => end(t$.hung);
})();
</script>
</body>
</html>
"""


BUTTON_LABELS = {"ar": "اتصل بالعربي", "en": "Call in English"}


def _persona_picker(personas: list[dict], languages: list[str]) -> str:
    if not personas:
        return ""
    chips = []
    for index, persona in enumerate(personas):
        names = []
        for lang in languages:
            name = persona["name"].get(lang)
            if name and name not in names:
                names.append(name)
        checked = " checked" if index == 0 else ""
        chips.append(
            f'<label class="chip"><input type="radio" name="persona" value="{escape(persona["id"], quote=True)}"{checked}>'
            f'<span dir="auto">{escape(" · ".join(names))}</span></label>'
        )
    return (
        '<div class="who"><p><span dir="rtl">تحب تكلم مين؟</span> · Who would you like to talk to?</p>'
        f'<div class="chips">{"".join(chips)}</div></div>'
    )


def render_page(*, title: str, languages: list[str], personas: list[dict] | None = None) -> str:
    buttons = "\n    ".join(
        f'<button class="call" data-lang="{escape(lang, quote=True)}" lang="{escape(lang, quote=True)}">'
        f'{escape(BUTTON_LABELS.get(lang.split("-")[0], f"Call ({lang})"))}</button>'
        for lang in languages
    )
    first = escape(languages[0].split("-")[0], quote=True)
    return (
        _PAGE.replace("__TITLE__", escape(title))
        .replace("__LANG__", first)
        .replace("__BUTTONS__", buttons)
        .replace("__PERSONAS__", _persona_picker(personas or [], languages))
    )
