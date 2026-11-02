"""The browser call page. One self-contained HTML document, no CDN: the
portraits, backdrop and Cloudastick branding are all drawn inline.

Turn-based on purpose, like the engine: play the prompt, listen until the
caller stops talking, upload one 16 kHz mono WAV, play the next prompt.
"""

from __future__ import annotations

from html import escape

from .avatars import portrait

_PAGE = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>__TITLE__</title>
<style>
:root{
  --bg:#060a1c;--bg2:#0e1433;--ink:#eef2ff;--muted:#a3aed0;--glass:rgba(255,255,255,.06);--glass-2:rgba(255,255,255,.11);
  --edge:rgba(255,255,255,.13);--a1:#38bdf8;--a2:#818cf8;--a3:#e879f9;--ok:#34d399;--danger:#fb7185;
  --brand:rgba(165,180,252,.13);--blob:.55;--shadow:0 30px 80px -30px rgba(0,0,0,.75);
  --spring:cubic-bezier(.34,1.56,.64,1);--ease:cubic-bezier(.2,.8,.2,1);
}
@media (prefers-color-scheme:light){:root{
  --bg:#eef2ff;--bg2:#fdf4ff;--ink:#0f172a;--muted:#55607a;--glass:rgba(255,255,255,.55);--glass-2:rgba(255,255,255,.85);
  --edge:rgba(30,41,90,.1);--brand:rgba(79,70,229,.1);--blob:.35;--shadow:0 30px 70px -30px rgba(30,41,90,.35)}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;min-height:100dvh;color:var(--ink);overflow-x:hidden;
  background:linear-gradient(160deg,var(--bg),var(--bg2));
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Tahoma,sans-serif;-webkit-font-smoothing:antialiased}

/* The moving backdrop: colour blobs, drifting clouds and the brand wordmark. */
.bg{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.blob{position:absolute;width:70vmax;height:70vmax;border-radius:50%;filter:blur(70px);opacity:var(--blob);animation:drift 26s ease-in-out infinite alternate}
.b1{background:radial-gradient(circle,var(--a1),transparent 60%);top:-30vmax;left:-25vmax}
.b2{background:radial-gradient(circle,var(--a2),transparent 60%);top:10vh;right:-35vmax;animation-duration:32s;animation-delay:-8s}
.b3{background:radial-gradient(circle,var(--a3),transparent 60%);bottom:-40vmax;left:-10vmax;animation-duration:38s;animation-delay:-16s}
.brand{position:absolute;inset:-30% -50%;display:flex;flex-direction:column;justify-content:space-around;transform:rotate(-14deg)}
.brand div{display:flex;width:max-content;white-space:nowrap;font-weight:800;letter-spacing:-.03em;
  font-size:clamp(44px,11vw,120px);line-height:1;color:transparent;-webkit-text-stroke:1px var(--brand);animation:slide 70s linear infinite}
.brand div:nth-child(even){animation-direction:reverse;animation-duration:90s}
.brand div:nth-child(3n){color:var(--brand);-webkit-text-stroke:0;opacity:.5}
.brand span{padding-inline-end:.4em}
.cloud{position:absolute;color:var(--ink);opacity:.06;animation:float 60s linear infinite}
.c1{top:12%;width:160px;animation-delay:-10s}
.c2{top:48%;width:240px;animation-duration:85s;animation-delay:-50s}
.c3{top:78%;width:120px;animation-duration:50s;animation-delay:-30s}

main{position:relative;z-index:1;max-width:540px;margin:0 auto;min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;gap:16px;
  padding:max(20px,env(safe-area-inset-top)) 16px max(18px,env(safe-area-inset-bottom))}
header{animation:rise .8s var(--ease) both}
.pill{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.02em;
  color:var(--muted);background:var(--glass);border:1px solid var(--edge);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.pill i{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 var(--ok);animation:beat 2s infinite}
h1{font-size:clamp(26px,7vw,36px);line-height:1.15;letter-spacing:-.02em;margin:12px 0 6px;
  background:linear-gradient(100deg,var(--ink) 30%,var(--a2) 60%,var(--a1));-webkit-background-clip:text;background-clip:text;color:transparent;
  background-size:200% 100%;animation:sheen 8s ease-in-out infinite alternate}
p.sub{color:var(--muted);margin:0;font-size:14px}
.card{position:relative;background:var(--glass);border:1px solid var(--edge);border-radius:28px;padding:18px 16px;
  backdrop-filter:blur(26px) saturate(170%);-webkit-backdrop-filter:blur(26px) saturate(170%);box-shadow:var(--shadow);animation:rise .9s .08s var(--ease) both}

/* Who to talk to: one card each, the chosen one glows and its ring morphs. */
.who p{margin:0 0 12px;color:var(--muted);font-size:14px;text-align:center}
.people{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:12px}
.persona{position:relative;display:flex;flex-direction:column;align-items:center;gap:12px;padding:20px 10px 16px;border-radius:22px;cursor:pointer;
  background:var(--glass);border:1px solid var(--edge);transition:transform .55s var(--spring),background .3s,box-shadow .4s,border-color .3s;
  animation:rise .8s var(--ease) both;-webkit-tap-highlight-color:transparent}
.persona:nth-child(2){animation-delay:.12s}.persona:nth-child(3){animation-delay:.2s}.persona:nth-child(n+4){animation-delay:.28s}
.persona input{position:absolute;opacity:0;pointer-events:none}
.persona:hover{transform:translateY(-3px)}
.persona:active{transform:scale(.97)}
.persona:has(input:checked){background:var(--glass-2);border-color:transparent;transform:translateY(-4px) scale(1.03);
  box-shadow:0 0 0 2px var(--a2),0 22px 44px -18px var(--a2)}
.persona:has(input:focus-visible){outline:2px solid var(--a1);outline-offset:4px}
.persona:has(input:disabled){cursor:default}
.pname{font-weight:650;font-size:15px;text-align:center}
.tag{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.tag::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ok)}
.tick{position:absolute;top:10px;inset-inline-end:10px;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--a1),var(--a2));transform:scale(0);transition:transform .45s var(--spring)}
.persona:has(input:checked) .tick{transform:scale(1)}

.portrait{position:relative;width:96px;height:96px;display:grid;place-items:center;flex:none}
.portrait svg{position:relative;z-index:2;width:100%;height:100%;border-radius:50%;display:block;
  box-shadow:0 12px 30px -10px rgba(0,0,0,.5),inset 0 0 0 1px rgba(255,255,255,.2);transition:filter .4s,transform .5s var(--spring)}
.persona:not(:has(input:checked)) .portrait svg{filter:saturate(.55) brightness(.9)}
.persona:has(input:checked) .portrait svg{transform:scale(1.04)}
.morph{position:absolute;z-index:1;inset:-9px;opacity:0;transition:opacity .5s,inset .15s;
  background:conic-gradient(from 0deg,var(--a1),var(--a2),var(--a3),var(--a1));
  border-radius:42% 58% 63% 37%/41% 44% 56% 59%;animation:morph 9s ease-in-out infinite,spin 16s linear infinite}
.persona:has(input:checked) .morph{opacity:1}
.persona:has(input:checked) .portrait{view-transition-name:hero}

/* The call itself: the chosen portrait takes the middle and follows the voice. */
.stage{display:none;flex-direction:column;align-items:center;gap:10px;padding:10px 0 6px;--level:0}
body.in-call .stage,body.solo .stage{display:flex}
body.in-call .who{display:none}
.stage .portrait{width:clamp(136px,42vw,176px);height:clamp(136px,42vw,176px)}
.stage .portrait.on{view-transition-name:hero}
.stage .morph{opacity:1;inset:calc(-12px - var(--level) * 16px)}
.halo{position:absolute;z-index:0;inset:-10px;border-radius:50%;border:2px solid var(--a1);opacity:0}
body[data-state=speaking] .halo{animation:ripple 2.1s var(--ease) infinite}
body[data-state=speaking] .halo:nth-of-type(2){animation-delay:.7s}
body[data-state=speaking] .halo:nth-of-type(3){animation-delay:1.4s}
body[data-state=listening] .halo:first-of-type{opacity:.9;border-color:var(--ok);inset:calc(-16px - var(--level) * 22px);transition:inset .08s}
.orbit{position:absolute;z-index:3;inset:-22px;opacity:0;transition:opacity .4s;animation:spin 1.6s linear infinite}
.orbit i{position:absolute;width:9px;height:9px;border-radius:50%;background:var(--a1);box-shadow:0 0 12px var(--a1)}
.orbit i:nth-child(1){top:0;left:50%}.orbit i:nth-child(2){bottom:12%;left:6%;background:var(--a2)}.orbit i:nth-child(3){bottom:12%;right:6%;background:var(--a3)}
body[data-state=thinking] .orbit,body[data-state=connecting] .orbit{opacity:1}
body[data-state=queued] .stage .portrait{animation:breathe 3.2s ease-in-out infinite}
.stage-name{font-weight:700;font-size:20px;letter-spacing:-.01em;margin-top:8px}
.bars{display:flex;align-items:center;justify-content:center;gap:5px;height:46px}
.bars i{--k:1;width:5px;border-radius:3px;background:linear-gradient(var(--a1),var(--a2));
  height:calc(6px + var(--level) * 38px * var(--k));transition:height .09s,opacity .3s;opacity:.35}
body[data-state=speaking] .bars i,body[data-state=listening] .bars i{opacity:1}
body[data-state=listening] .bars i{background:linear-gradient(var(--ok),var(--a1))}
body[data-state=thinking] .bars i,body[data-state=connecting] .bars i{opacity:.9;height:10px;animation:wave 1s ease-in-out infinite}
.bars i:nth-child(1),.bars i:nth-child(9){--k:.35}.bars i:nth-child(2),.bars i:nth-child(8){--k:.6}
.bars i:nth-child(3),.bars i:nth-child(7){--k:.85}.bars i:nth-child(4),.bars i:nth-child(6){--k:1.05}.bars i:nth-child(5){--k:1.2}
.bars i:nth-child(2){animation-delay:.1s}.bars i:nth-child(3){animation-delay:.2s}.bars i:nth-child(4){animation-delay:.3s}.bars i:nth-child(5){animation-delay:.4s}
.bars i:nth-child(6){animation-delay:.5s}.bars i:nth-child(7){animation-delay:.6s}.bars i:nth-child(8){animation-delay:.7s}.bars i:nth-child(9){animation-delay:.8s}

#log{display:flex;flex-direction:column;gap:8px;max-height:40vh;overflow-y:auto;margin:16px 0 4px;padding:4px 2px;scroll-behavior:smooth;
  -webkit-mask-image:linear-gradient(transparent,#000 18px);mask-image:linear-gradient(transparent,#000 18px)}
#log:empty{display:none}
.line{padding:10px 14px;border-radius:18px;max-width:88%;font-size:15px;unicode-bidi:plaintext;animation:pop .5s var(--spring) both}
.agent{align-self:flex-start;background:var(--glass-2);border:1px solid var(--edge);border-end-start-radius:6px}
.you{align-self:flex-end;color:#fff;background:linear-gradient(135deg,#6366f1,#0ea5e9);border-end-end-radius:6px;box-shadow:0 10px 24px -14px #6366f1}

.row{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:16px}
button{font:inherit;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}
.call,#hang{position:relative;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;gap:10px;min-height:54px;
  padding:14px 22px;border-radius:999px;font-weight:650;color:#fff;transition:transform .35s var(--spring),box-shadow .3s,opacity .3s,filter .3s}
.call{flex:1 1 150px;background:linear-gradient(120deg,#0ea5e9,#6366f1 55%,#c026d3);background-size:180% 100%;
  box-shadow:0 16px 34px -16px #6366f1;animation:sheen 6s ease-in-out infinite alternate}
.call::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.35) 50%,transparent 70%);
  transform:translateX(-100%);animation:shine 3.6s ease-in-out infinite}
.call:hover:not(:disabled),#hang:hover{transform:translateY(-2px)}
.call:active:not(:disabled),#hang:active{transform:scale(.96)}
.call:disabled{opacity:.45;filter:grayscale(.5);cursor:not-allowed;box-shadow:none}
.call:disabled::after{display:none}
.call svg,#hang svg{width:20px;height:20px;flex:none}
#hang{display:none;flex:1 1 100%;background:linear-gradient(120deg,#f43f5e,#e11d48);box-shadow:0 16px 34px -16px #f43f5e}
#hang svg{transform:rotate(135deg)}
#status{flex:1 1 100%;min-height:1.5em;text-align:center;color:var(--muted);font-size:14px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--ok);margin-inline-end:6px;animation:p 1s infinite}

footer{margin-top:auto;padding-top:8px;text-align:center;font-size:13px;color:var(--muted);animation:rise 1s .2s var(--ease) both}
footer a{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;color:inherit;text-decoration:none;
  background:var(--glass);border:1px solid var(--edge);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);transition:transform .35s var(--spring),box-shadow .3s}
footer a:hover{transform:translateY(-2px);box-shadow:0 12px 28px -14px var(--a2)}
footer b{font-weight:750;background:linear-gradient(100deg,var(--a1),var(--a2),var(--a3));-webkit-background-clip:text;background-clip:text;color:transparent}
footer svg{width:20px;height:14px}

@media (min-width:720px){main{max-width:600px;padding-top:48px;gap:20px}.card{padding:26px}.portrait{width:112px;height:112px}}

::view-transition-group(hero){animation-duration:.7s;animation-timing-function:var(--ease)}
::view-transition-old(root),::view-transition-new(root){animation-duration:.45s}

@keyframes drift{to{transform:translate(12vmax,8vmax) scale(1.15)}}
@keyframes slide{to{transform:translateX(-50%)}}
@keyframes float{from{transform:translateX(-30vw)}to{transform:translateX(130vw)}}
@keyframes rise{from{opacity:0;transform:translateY(18px) scale(.98);filter:blur(6px)}}
@keyframes pop{from{opacity:0;transform:translateY(10px) scale(.92)}}
@keyframes morph{0%,100%{border-radius:42% 58% 63% 37%/41% 44% 56% 59%}33%{border-radius:63% 37% 44% 56%/52% 61% 39% 48%}66%{border-radius:37% 63% 51% 49%/62% 38% 62% 38%}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes ripple{from{opacity:.8;transform:scale(1)}to{opacity:0;transform:scale(1.55)}}
@keyframes breathe{50%{transform:scale(.95)}}
@keyframes wave{50%{transform:scaleY(2.6)}}
@keyframes sheen{to{background-position:100% 0}}
@keyframes shine{60%,100%{transform:translateX(100%)}}
@keyframes beat{70%{box-shadow:0 0 0 8px transparent}100%{box-shadow:0 0 0 0 transparent}}
@keyframes p{50%{opacity:.3}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
  ::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation:none!important}}
</style>
</head>
<body data-state="idle"__BODY_CLASS__>
<div class="bg" aria-hidden="true">
  <div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div>
  <div class="brand">__BRAND__</div>
  <svg class="cloud c1" viewBox="0 0 110 64"><path fill="currentColor" d="M26 62a24 24 0 0 1-2-48A30 30 0 0 1 80 12a25 25 0 0 1 4 50z"/></svg>
  <svg class="cloud c2" viewBox="0 0 110 64"><path fill="currentColor" d="M26 62a24 24 0 0 1-2-48A30 30 0 0 1 80 12a25 25 0 0 1 4 50z"/></svg>
  <svg class="cloud c3" viewBox="0 0 110 64"><path fill="currentColor" d="M26 62a24 24 0 0 1-2-48A30 30 0 0 1 80 12a25 25 0 0 1 4 50z"/></svg>
</div>
<main>
<header>
  <span class="pill"><i></i>Live voice line · <span dir="rtl">خط صوتي مباشر</span></span>
  <h1>__TITLE__</h1>
  <p class="sub">Choose a language, then allow the microphone. <span dir="rtl">اختار اللغة، وبعدين اسمح باستخدام المايك.</span></p>
</header>
<section class="card">
  __PERSONAS__
  <div class="stage" id="stage">
    __STAGE__
    <div class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
  </div>
  <div id="log" aria-live="polite"></div>
  <div class="row">
    __BUTTONS__
    <button id="hang"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/></svg><span>Hang up</span></button>
    <span id="status"></span>
  </div>
</section>
<footer>
  <a href="https://cloudastick.com" target="_blank" rel="noopener">
    <svg viewBox="0 0 110 64" aria-hidden="true"><defs><linearGradient id="cs-logo" x1="0" x2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#c026d3"/></linearGradient></defs><path fill="url(#cs-logo)" d="M26 62a24 24 0 0 1-2-48A30 30 0 0 1 80 12a25 25 0 0 1 4 50z"/></svg>
    <span>Powered by <b>Cloudastick</b></span>
  </a>
</footer>
</main>
<script>
(() => {
  const base = location.pathname.replace(/\\/$/, "");
  const $ = (id) => document.getElementById(id);
  const logEl = $("log"), statusEl = $("status"), hangBtn = $("hang");
  const callBtns = [...document.querySelectorAll(".call")];
  const stage = $("stage"), stageName = $("stage-name");
  const setState = (s) => { document.body.dataset.state = s; };

  // The portrait follows the voice: the caller's microphone while listening,
  // the agent's audio while speaking. `target` is set by whichever is live.
  let level = 0, target = 0, analyser = null, wave = null;
  (function tick() {
    if (analyser && document.body.dataset.state === "speaking") {
      analyser.getByteTimeDomainData(wave);
      let sum = 0; for (let i = 0; i < wave.length; i++) { const v = (wave[i] - 128) / 128; sum += v * v; }
      target = Math.min(1, Math.sqrt(sum / wave.length) * 5);
    }
    level += (target - level) * 0.3; target *= 0.9;
    stage.style.setProperty("--level", level.toFixed(3));
    requestAnimationFrame(tick);
  })();

  // Morph the chosen card's portrait into the middle of the call, and back.
  function scene(inCall) {
    if (document.body.classList.contains("in-call") === inCall) return;
    const go = () => {
      const who = persona(), picked = document.querySelector('input[name="persona"]:checked');
      stage.querySelectorAll(".portrait[data-for]").forEach((p) => {
        const on = p.dataset.for === who; p.hidden = !on; p.classList.toggle("on", on);
      });
      if (stageName && picked) stageName.textContent = picked.dataset.name;
      document.body.classList.toggle("in-call", inCall);
    };
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(go);
    else go();
  }
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
    setState("queued");
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

  async function post(path, body, extra) {
    const res = await fetch(base + path, {
      method: "POST", body: body || null,
      headers: { ...(body ? { "Content-Type": "audio/wav" } : {}), ...(extra || {}) },
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
      if (!analyser) { analyser = ctx.createAnalyser(); analyser.fftSize = 512; wave = new Uint8Array(analyser.fftSize); }
      node.buffer = audio; node.connect(ctx.destination); node.connect(analyser); node.onended = resolve; node.start();
    });
  }

  // Record one answer: wait up to `timeout` s for speech, stop after a pause.
  // Half a second before the detected start is kept, so the first syllable of
  // a short answer (a name) is not cut off. The noise floor follows the room
  // while nobody is talking instead of being guessed from the first frames.
  function listen(spec) {
    return new Promise((resolve) => {
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [], preroll = [], all = []; const started = performance.now();
      const prerollChunks = Math.ceil((0.5 * ctx.sampleRate) / 4096);
      const pauseMs = spec.speech_timeout === "auto" ? 1300 : Math.max(500, Number(spec.speech_timeout) * 1000 || 1300);
      let noise = 0.004, speaking = false, lastVoice = 0, voiced = 0, peak = 0, firstVoice = null, why = "";
      proc.onaudioprocess = (e) => {
        if (!live) { why = "hung_up"; finish(false); return; }
        const data = new Float32Array(e.inputBuffer.getChannelData(0));
        if (spec.debug && all.length * 4096 < ctx.sampleRate * 30) all.push(data);
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length); const now = performance.now();
        peak = Math.max(peak, rms); target = Math.min(1, rms * 14);
        const threshold = Math.max(0.005, noise * 3);
        if (!speaking) {
          if (rms > threshold) {
            speaking = true; lastVoice = now; firstVoice = now - started; chunks.push(...preroll, data); voiced++;
          } else {
            noise = noise * 0.9 + rms * 0.1;
            preroll.push(data); if (preroll.length > prerollChunks) preroll.shift();
            if (now - started > spec.timeout * 1000) { why = "no_speech_before_timeout"; finish(false); }
          }
          return;
        }
        chunks.push(data);
        if (rms > threshold) { lastVoice = now; voiced++; }
        if (now - lastVoice > pauseMs) { why = voiced > 1 ? "pause" : "too_short"; finish(voiced > 1); }
        else if (now - started > 30000) { why = "max_length"; finish(true); }
      };
      let done = false;
      function finish(heard) {
        if (done) return; done = true;
        proc.disconnect(); source.disconnect(proc);
        // What the speech detector saw, for tuning (sent only with debug on).
        const diag = {
          sample_rate: ctx.sampleRate, ended: why, detected: heard,
          noise_floor: +noise.toFixed(5), threshold: +Math.max(0.005, noise * 3).toFixed(5),
          peak: +peak.toFixed(5), voiced_chunks: voiced, first_voice_ms: firstVoice && Math.round(firstVoice),
          window_ms: Math.round(performance.now() - started),
        };
        const blob = spec.debug ? wav(all, ctx.sampleRate) : heard ? wav(chunks, ctx.sampleRate) : new Blob([]);
        resolve({ blob, heard, diag });
      }
      source.connect(proc); proc.connect(ctx.destination);
      setState("listening"); status('<span class="dot"></span>' + t$.listening);
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
        if (clip.audio && live) { setState("speaking"); status(t$.speaking); await play(clip.audio); }
      }
      if (t.done || !t.listen || !live) break;
      if (t.listen.beep !== false) await beep();
      const answer = await listen(t.listen);
      if (!live) break;
      setState("thinking"); status(t$.thinking);
      const q = new URLSearchParams({ call_id: t.call_id, step: t.listen.step, attempt: t.listen.attempt, turn: t.listen.turn });
      document.querySelectorAll('input[name="persona"]').forEach((i) => { i.disabled = true; });
      t = await post("/turn?" + q, answer.blob, t.listen.debug
        ? { "X-Voice-Detected": answer.heard ? "1" : "0", "X-Voice-Diag": JSON.stringify(answer.diag) } : {});
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
    setState("idle"); scene(false);
    status(message);
    setTimeout(refreshReady, 4000);
  }

  async function call(lang) {
    t$ = TEXT[lang.split("-")[0]] || TEXT.en;
    hangBtn.lastElementChild.textContent = t$.hang;
    callBtns.forEach((b) => { b.disabled = true; }); setState("connecting"); status(t$.connecting);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      source = ctx.createMediaStreamSource(stream);
      live = true; logEl.textContent = "";
      callBtns.forEach((b) => { b.style.display = "none"; }); hangBtn.style.display = "inline-flex";
      scene(true);
      const who = persona();
      let first = await post("/start?lang=" + encodeURIComponent(lang) + (who ? "&persona=" + encodeURIComponent(who) : ""));
      if (first.queued) first = await waitInLine(first);
      if (first) await handle(first);
    } catch (err) {
      end(t$.failed + err.message);
    }
  }
  callBtns.forEach((b) => { b.onclick = () => call(b.dataset.lang); });

  // A voice opens for calls only when every line of it is natural. Until then
  // its button waits and shows progress, refreshed every 10 s.
  let readyTimer = null;
  async function refreshReady() {
    clearTimeout(readyTimer);
    if (live) return;
    let data;
    try { data = await (await fetch(base + "/ready", { cache: "no-store" })).json(); } catch (e) { return; }
    const who = persona();
    const names = {};
    document.querySelectorAll('input[name="persona"]').forEach((i) => { names[i.value] = i.dataset.name; });
    let waiting = [];
    callBtns.forEach((b) => {
      const o = (data.options || []).find((x) => (x.persona || null) === who && x.language === b.dataset.lang);
      const ok = !o || o.ok;
      b.disabled = !ok;
      if (!ok) waiting.push(o);
    });
    if (waiting.length) {
      const o = waiting[0], name = who ? names[who] + " " : "";
      status("تحضير صوت " + name + "… " + o.ready + "/" + o.total + " · Preparing " + name + "voice… " + o.ready + "/" + o.total);
      readyTimer = setTimeout(refreshReady, 10000);
    } else if (!live) {
      status("");
    }
  }
  document.querySelectorAll('input[name="persona"]').forEach((i) => i.addEventListener("change", refreshReady));
  refreshReady();
  hangBtn.onclick = () => end(t$.hung);
})();
</script>
</body>
</html>
"""


BUTTON_LABELS = {"ar": "اتصل بالعربي", "en": "Call in English"}

_PHONE = (
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2'
    'a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1'
    'c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/></svg>'
)
_TICK = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
_RINGS = '<span class="morph"></span><i class="halo"></i><i class="halo"></i><i class="halo"></i><span class="orbit"><i></i><i></i><i></i></span>'
# The backdrop's wordmark: four rows, each written twice so the slide loops.
_BRAND = "".join(f"<div><span>{'cloudastick.com ✦ ' * 4}</span><span>{'cloudastick.com ✦ ' * 4}</span></div>" for _ in range(4))


def _display_name(persona: dict, languages: list[str]) -> str:
    names = []
    for lang in languages:
        name = persona["name"].get(lang)
        if name and name not in names:
            names.append(name)
    return " · ".join(names) or persona["id"]


def _persona_picker(personas: list[dict], languages: list[str]) -> str:
    if not personas:
        return ""
    cards = []
    for index, persona in enumerate(personas):
        name = _display_name(persona, languages)
        checked = " checked" if index == 0 else ""
        cards.append(
            f'<label class="persona"><input type="radio" name="persona" value="{escape(persona["id"], quote=True)}"{checked}'
            f' data-name="{escape(name, quote=True)}">'
            f'<span class="tick">{_TICK}</span>'
            f'<span class="portrait"><span class="morph"></span>{portrait(persona, "p-" + persona["id"], name)}</span>'
            f'<span class="pname" dir="auto">{escape(name)}</span><span class="tag">Online · <span dir="rtl">متاح</span></span></label>'
        )
    return (
        '<div class="who"><p><span dir="rtl">تحب تكلم مين؟</span> · Who would you like to talk to?</p>'
        f'<div class="people">{"".join(cards)}</div></div>'
    )


def _stage(personas: list[dict], languages: list[str], title: str) -> str:
    if not personas:
        return f'<span class="portrait on">{_RINGS}{portrait(None, "s-solo", title)}</span>'
    out = [
        f'<span class="portrait" data-for="{escape(p["id"], quote=True)}" hidden>{_RINGS}'
        f'{portrait(p, "s-" + p["id"], _display_name(p, languages))}</span>'
        for p in personas
    ]
    return "".join(out) + '<div class="stage-name" id="stage-name" dir="auto"></div>'


def render_page(*, title: str, languages: list[str], personas: list[dict] | None = None) -> str:
    personas = personas or []
    buttons = "\n    ".join(
        f'<button class="call" data-lang="{escape(lang, quote=True)}" lang="{escape(lang, quote=True)}">{_PHONE}'
        f'<span>{escape(BUTTON_LABELS.get(lang.split("-")[0], f"Call ({lang})"))}</span></button>'
        for lang in languages
    )
    first = escape(languages[0].split("-")[0], quote=True)
    return (
        _PAGE.replace("__TITLE__", escape(title))
        .replace("__LANG__", first)
        .replace("__BODY_CLASS__", "" if personas else ' class="solo"')
        .replace("__BRAND__", _BRAND)
        .replace("__BUTTONS__", buttons)
        .replace("__STAGE__", _stage(personas, languages, title))
        .replace("__PERSONAS__", _persona_picker(personas, languages))
    )
