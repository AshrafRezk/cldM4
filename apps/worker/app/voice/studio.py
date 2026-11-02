"""Recording studio: staff read each script line once, in their own voice.

A person reading the questions is the most natural voice there is, and it
never leaves the Mini. A tenant mints a studio link for a script (Bearer +
`voice`, valid 7 days); the page lists every line callers can hear, in every
language, with what plays today, and lets someone record, listen back, save,
or delete it. Saved takes are cleaned up by `VoiceAudio.save_recording` and
win over any generated audio on the next call.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..errors import CloudiatorError
from .engine import languages_of

STUDIO_TTL_SECONDS = 7 * 86400
LINE_LABELS = {"greeting": "Greeting", "goodbye": "Closing", "__fail__": "If no answer", "__hold__": "On hold"}


def register_studio_routes(app: FastAPI, *, engine, audio, require_key) -> None:
    store = engine.store

    @app.post("/v1/voice/scripts/{script_id}/studio-link")
    async def create_studio_link(script_id: str, request: Request, key=Depends(require_key("voice"))) -> JSONResponse:
        if store.script_by_id(key.tenant_id, script_id) is None:
            raise CloudiatorError(404, "script_not_found", "No active script with that id.")
        token = store.create_web_link(key.tenant_id, script_id, prefix="st_")
        request.state.usage.tool = "voice_studio_link"
        return JSONResponse(
            content={
                "script_id": script_id,
                "url": f"{engine.base_url}/v1/voice/studio/{token}",
                "expires_in": STUDIO_TTL_SECONDS,
                "note": "Shown once. Anyone with this URL can replace this script's recordings for 7 days.",
            }
        )

    def studio(request: Request, token: str) -> tuple[str, dict[str, Any]]:
        found = store.web_link(token, prefix="st_", max_age_seconds=STUDIO_TTL_SECONDS)
        if found is None:
            raise CloudiatorError(404, "link_not_found", "This studio link is not valid or has expired.")
        tenant_id, script_id = found
        event = getattr(request.state, "usage", None)
        if event is not None:
            event.tenant_id = tenant_id
        script = store.script_by_id(tenant_id, script_id)
        if script is None:
            raise CloudiatorError(404, "script_not_found", "The script for this studio link is gone.")
        return tenant_id, script[1]

    def line_for(script: dict[str, Any], step: str, language: str, persona: str | None) -> dict[str, str]:
        for line in audio.lines(script):
            if line["key"] == step and line["language"] == language and line.get("persona") == persona:
                return line
        raise CloudiatorError(404, "line_not_found", "That script has no such line.")

    @app.get("/v1/voice/studio/{token}")
    async def studio_page(token: str, request: Request) -> HTMLResponse:
        _tenant_id, script = studio(request, token)
        return HTMLResponse(
            render_studio(script.get("display_name") or script["id"]),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                     "Permissions-Policy": "microphone=(self)"},
        )

    @app.get("/v1/voice/studio/{token}/lines")
    async def studio_lines(token: str, request: Request) -> JSONResponse:
        tenant_id, script = studio(request, token)
        status = {
            (row["key"], row["language"], row.get("persona")): row["source"]
            for row in audio.status(tenant_id, script)
        }
        lines = [
            {**line, "label": LINE_LABELS.get(line["key"], line["key"]),
             "source": status.get((line["key"], line["language"], line.get("persona")), "fallback")}
            for line in audio.lines(script)
        ]
        personas = [{"id": p["id"], "name": p["name"]} for p in script.get("personas") or []]
        return JSONResponse(content={"script_id": script["id"], "languages": languages_of(script),
                                     "personas": personas, "engine": audio.engine, "lines": lines})

    @app.get("/v1/voice/studio/{token}/audio/{step}/{language}")
    async def studio_audio(token: str, step: str, language: str, request: Request) -> JSONResponse:
        tenant_id, script = studio(request, token)
        persona = request.query_params.get("persona") or None
        line = line_for(script, step, language, persona)
        data_url, source = await audio.clip(
            tenant_id=tenant_id, script=script, key=step, language=language, text=line["text"], persona=persona
        )
        return JSONResponse(content={"audio": data_url, "source": source})

    @app.put("/v1/voice/studio/{token}/recordings/{step}/{language}")
    async def studio_save(token: str, step: str, language: str, request: Request) -> JSONResponse:
        tenant_id, script = studio(request, token)
        persona = request.query_params.get("persona") or None
        line_for(script, step, language, persona)
        body = await request.body()
        if not body or len(body) > 5_000_000:
            raise CloudiatorError(400, "invalid_request_error", "Send 1 byte to 5 MB of audio.")
        try:
            await audio.save_recording(tenant_id, script["id"], step, language, body, persona)
        except Exception as exc:  # noqa: BLE001
            raise CloudiatorError(400, "invalid_audio", "That audio could not be read.") from exc
        request.state.usage.tool = "voice_recording"
        return JSONResponse(content={"step": step, "language": language, "source": "recording"})

    @app.delete("/v1/voice/studio/{token}/recordings/{step}/{language}")
    async def studio_delete(token: str, step: str, language: str, request: Request) -> JSONResponse:
        tenant_id, script = studio(request, token)
        persona = request.query_params.get("persona") or None
        line_for(script, step, language, persona)
        return JSONResponse(content={"deleted": audio.delete_recording(tenant_id, script["id"], step, language, persona)})


def render_studio(title: str) -> str:
    return _STUDIO.replace("__TITLE__", escape(title))


_STUDIO = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Studio — __TITLE__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--accent:#1f6f5c;--rec:#b3261e;--ok:#1f6f5c;--chip:#eef4f2}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecece8;--muted:#9a9a93;--line:#30302d;--accent:#5fbfa5;--rec:#f2b8b5;--ok:#5fbfa5;--chip:#1f2b28}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}
p.sub{color:var(--muted);margin:0 0 20px;font-size:14px}
h2{font-size:15px;margin:24px 0 8px;color:var(--muted);font-weight:600}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:10px}
.head{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.chip{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip)}
.chip.recording{color:var(--ok);font-weight:600}
.text{unicode-bidi:plaintext;margin:0 0 10px;font-size:16px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
button{font:inherit;font-size:14px;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:6px 14px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.rec{background:var(--rec);border-color:var(--rec);color:#fff}
button:disabled{opacity:.45;cursor:default}
.msg{font-size:13px;color:var(--muted)}
</style>
</head>
<body>
<main>
<h1>Recording studio — __TITLE__</h1>
<p class="sub">Read each line the way you would say it to a caller. Recordings replace the generated voice on the next call. Use a quiet room and keep the microphone at the same distance for every line.</p>
<div id="lines">Loading…</div>
</main>
<script>
(() => {
  const base = location.pathname.replace(/\\/$/, "");
  const root = document.getElementById("lines");
  const SOURCE = { recording: "your recording", rendered: "generated voice", fallback: "basic voice (rendering)", none: "no audio" };
  let ctx = null, recorder = null;

  async function json(path, opts) {
    const res = await fetch(base + path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data.error && data.error.message) || ("HTTP " + res.status));
    return data;
  }
  async function playUrl(url) {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    const buf = await ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());
    const node = ctx.createBufferSource(); node.buffer = buf; node.connect(ctx.destination); node.start();
    return new Promise((r) => { node.onended = r; });
  }

  function card(line) {
    const el = document.createElement("div"); el.className = "item";
    const head = document.createElement("div"); head.className = "head";
    const label = document.createElement("span"); label.className = "label"; label.textContent = line.label;
    const chip = document.createElement("span"); chip.className = "chip " + line.source; chip.textContent = SOURCE[line.source] || line.source;
    head.append(label, chip);
    const text = document.createElement("p"); text.className = "text"; text.dir = "auto"; text.textContent = line.text;
    const row = document.createElement("div"); row.className = "row";
    const btn = (label, cls) => { const b = document.createElement("button"); b.textContent = label; if (cls) b.className = cls; row.append(b); return b; };
    const play = btn("▶ Play current"), rec = btn("● Record", "rec"), listen = btn("▶ Listen"), save = btn("Save", "primary"), drop = btn("Discard"), del = btn("Use generated voice");
    const msg = document.createElement("span"); msg.className = "msg"; row.append(msg);
    let take = null, chunks = [];
    const path = "/" + encodeURIComponent(line.key) + "/" + encodeURIComponent(line.language)
      + (line.persona ? "?persona=" + encodeURIComponent(line.persona) : "");
    const sync = () => {
      listen.disabled = save.disabled = drop.disabled = !take;
      del.style.display = line.source === "recording" ? "" : "none";
      chip.className = "chip " + line.source; chip.textContent = SOURCE[line.source] || line.source;
    };
    play.onclick = async () => {
      msg.textContent = "Loading…";
      try { const a = await json("/audio" + path); msg.textContent = ""; if (a.audio) await playUrl(a.audio); }
      catch (e) { msg.textContent = e.message; }
    };
    rec.onclick = async () => {
      if (recorder && recorder.state === "recording") { recorder.stop(); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
        chunks = []; recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          take = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          rec.textContent = "● Record again"; msg.textContent = "Listen, then Save or Discard."; sync();
        };
        recorder.start(); rec.textContent = "■ Stop"; msg.textContent = "Recording… read the line, then Stop.";
      } catch (e) { msg.textContent = "Microphone: " + e.message; }
    };
    listen.onclick = () => take && playUrl(URL.createObjectURL(take));
    drop.onclick = () => { take = null; msg.textContent = ""; rec.textContent = "● Record"; sync(); };
    save.onclick = async () => {
      if (!take) return; msg.textContent = "Saving…";
      try {
        await json("/recordings" + path, { method: "PUT", body: take, headers: { "Content-Type": take.type } });
        take = null; line.source = "recording"; rec.textContent = "● Record"; msg.textContent = "Saved. Callers hear this now."; sync();
      } catch (e) { msg.textContent = e.message; }
    };
    del.onclick = async () => {
      msg.textContent = "Removing…";
      try { await json("/recordings" + path, { method: "DELETE" }); line.source = "rendered"; msg.textContent = "Back to the generated voice."; sync(); }
      catch (e) { msg.textContent = e.message; }
    };
    sync();
    el.append(head, text, row);
    return el;
  }

  json("/lines").then((data) => {
    root.textContent = "";
    const people = data.personas.length ? data.personas : [{ id: null, name: {} }];
    for (const p of people) {
      for (const lang of data.languages) {
        const h = document.createElement("h2");
        const who = p.id ? (p.name[lang] || p.id) + " — " : "";
        h.textContent = who + (lang.startsWith("ar") ? "العربي (" + lang + ")" : "English (" + lang + ")");
        root.append(h);
        data.lines.filter((l) => l.language === lang && (l.persona || null) === p.id).forEach((l) => root.append(card(l)));
      }
    }
  }).catch((e) => { root.textContent = e.message; });
})();
</script>
</body>
</html>
"""
