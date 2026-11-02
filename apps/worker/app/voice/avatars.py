"""Portraits for the call page: inline SVG, drawn here, nothing fetched.

A persona gets the woman or the man by the voice it speaks with (Mariam,
Ahmed, …); anyone else gets their initial. Every copy on a page has its own
`uid`, so gradient ids never collide when one copy is hidden.
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping

from .audio import VOICETUT_FEMALE, VOICETUT_MALE

_WOMAN = """<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="__LABEL__">
<defs>
<linearGradient id="__U__-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f472b6"/><stop offset="1" stop-color="#6d28d9"/></linearGradient>
<linearGradient id="__U__-coat" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14857a"/><stop offset="1" stop-color="#0b4f49"/></linearGradient>
<radialGradient id="__U__-skin" cx=".45" cy=".38" r=".75"><stop offset="0" stop-color="#ecbd97"/><stop offset="1" stop-color="#c98e68"/></radialGradient>
<linearGradient id="__U__-hair" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b2418"/><stop offset="1" stop-color="#1f130d"/></linearGradient>
</defs>
<rect width="200" height="200" fill="url(#__U__-bg)"/>
<circle cx="164" cy="34" r="62" fill="#fff" opacity=".1"/>
<circle cx="24" cy="176" r="44" fill="#fff" opacity=".06"/>
<path d="M58 96c-4-40 18-60 44-60s46 20 42 60c-2 26 6 46 14 62H44c8-16 16-36 14-62z" fill="url(#__U__-hair)"/>
<path d="M22 200c4-32 22-50 50-58l28 18 28-18c28 8 46 26 50 58z" fill="url(#__U__-coat)"/>
<path d="M80 142l20 26 20-26-6-4H86z" fill="#fdf2f8"/>
<path d="M70 143l16-5 14 32-20-14z" fill="#0a4540"/>
<path d="M130 143l-16-5-14 32 20-14z" fill="#0a4540"/>
<circle cx="100" cy="182" r="3" fill="#fcd34d"/>
<path d="M88 116h24v22c0 7-24 7-24 0z" fill="#c08661"/>
<ellipse cx="100" cy="92" rx="31" ry="37" fill="url(#__U__-skin)"/>
<path d="M68 92c-2-26 12-44 34-44 20 0 34 14 33 38-8-12-22-20-40-20-10 8-18 16-27 26z" fill="url(#__U__-hair)"/>
<path d="M69 86c-6 16-6 36 2 52l-9 2c-8-18-6-42 7-54z" fill="url(#__U__-hair)"/>
<path d="M131 82c6 18 6 40-2 56l9 2c8-20 6-44-7-58z" fill="url(#__U__-hair)"/>
<path d="M81 86c4-3 9-3 13-1M106 85c4-2 9-2 13 1" stroke="#2a1a14" stroke-width="2.2" stroke-linecap="round" fill="none"/>
<ellipse cx="88" cy="96" rx="3.4" ry="3.9" fill="#1f1512"/><ellipse cx="112" cy="96" rx="3.4" ry="3.9" fill="#1f1512"/>
<circle cx="89.2" cy="94.6" r="1.1" fill="#fff"/><circle cx="113.2" cy="94.6" r="1.1" fill="#fff"/>
<path d="M83 93c3-3 8-3 11-1M106 92c3-2 8-2 11 1" stroke="#1f1512" stroke-width="1.6" stroke-linecap="round" fill="none"/>
<circle cx="80" cy="106" r="6" fill="#f43f5e" opacity=".14"/><circle cx="120" cy="106" r="6" fill="#f43f5e" opacity=".14"/>
<path d="M100 99c-1.5 5-2.5 8 0 9.5 1.6.8 3 .2 4-.6" stroke="#a8694a" stroke-width="1.7" stroke-linecap="round" fill="none"/>
<path d="M91 114c6 3.5 12 3.5 18 0-2.5 6-15.5 6-18 0z" fill="#be4b5f"/>
<path d="M66 90c0-32 14-50 34-50s34 18 34 50" stroke="#f1f5f9" stroke-width="4" fill="none" stroke-linecap="round"/>
<rect x="127" y="82" width="11" height="20" rx="5.5" fill="#111827"/>
<path d="M133 101c0 16-8 22-20 22" stroke="#111827" stroke-width="2.6" fill="none" stroke-linecap="round"/>
<circle cx="112" cy="123" r="3.6" fill="#111827"/>
<circle cx="69" cy="110" r="2.4" fill="#fcd34d"/>
</svg>"""

_MAN = """<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="__LABEL__">
<defs>
<linearGradient id="__U__-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#1e3a8a"/></linearGradient>
<linearGradient id="__U__-suit" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b3756"/><stop offset="1" stop-color="#141a2e"/></linearGradient>
<radialGradient id="__U__-skin" cx=".45" cy=".38" r=".75"><stop offset="0" stop-color="#dba37c"/><stop offset="1" stop-color="#b47652"/></radialGradient>
</defs>
<rect width="200" height="200" fill="url(#__U__-bg)"/>
<circle cx="164" cy="34" r="62" fill="#fff" opacity=".1"/>
<circle cx="24" cy="176" r="44" fill="#fff" opacity=".06"/>
<path d="M18 200c4-34 22-52 52-60l30 14 30-14c30 8 48 26 52 60z" fill="url(#__U__-suit)"/>
<path d="M78 142l22 30 22-30-8-6H86z" fill="#f4f6fb"/>
<path d="M96 150h8l3 6-4 30h-6l-4-30z" fill="#0f766e"/>
<path d="M68 141l18-5 14 34-22-18z" fill="#36436a"/>
<path d="M132 141l-18-5-14 34 22-18z" fill="#36436a"/>
<path d="M86 116h28v24c0 7-28 7-28 0z" fill="#a96d4a"/>
<ellipse cx="66" cy="96" rx="6" ry="9" fill="#b47652"/><ellipse cx="134" cy="96" rx="6" ry="9" fill="#b47652"/>
<ellipse cx="100" cy="92" rx="34" ry="40" fill="url(#__U__-skin)"/>
<path d="M66 92c-2-30 14-46 36-46 22 0 36 14 33 44-3-10-8-18-14-21-10 4-30 6-46 2-5 5-8 12-9 21z" fill="#1c1410"/>
<path d="M68 100c2 22 14 36 32 36s30-14 32-36c-4 14-10 22-16 22-6-3-26-3-32 0-6 0-12-8-16-22z" fill="#2a1d16" opacity=".72"/>
<path d="M87 110c4-3 9-3 13-1 4-2 9-2 13 1-4 2.5-9 3-13 2-4 1-9 .5-13-2z" fill="#1c1410"/>
<path d="M92 117c5 3.5 11 3.5 16 0" stroke="#5b2e1e" stroke-width="2.4" fill="none" stroke-linecap="round"/>
<path d="M79 85c4-3 10-3 14-1M107 84c4-2 10-2 14 1" stroke="#1c1410" stroke-width="3.2" stroke-linecap="round" fill="none"/>
<ellipse cx="87" cy="95" rx="3.2" ry="3.6" fill="#1a1a1a"/><ellipse cx="113" cy="95" rx="3.2" ry="3.6" fill="#1a1a1a"/>
<circle cx="88.2" cy="93.8" r="1.1" fill="#fff"/><circle cx="114.2" cy="93.8" r="1.1" fill="#fff"/>
<path d="M100 97c-2 6-3 9 0 11 2 1 4 0 5-1" stroke="#8f5536" stroke-width="2" fill="none" stroke-linecap="round"/>
<path d="M62 96c0-34 16-54 38-54s38 20 38 54" stroke="#e5e7eb" stroke-width="5" fill="none" stroke-linecap="round"/>
<rect x="55" y="86" width="12" height="22" rx="6" fill="#111827"/><rect x="133" y="86" width="12" height="22" rx="6" fill="#111827"/>
<path d="M61 106c0 18 10 25 23 25" stroke="#111827" stroke-width="3" fill="none" stroke-linecap="round"/>
<circle cx="86" cy="131" r="4" fill="#111827"/>
</svg>"""

_INITIAL = """<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="__LABEL__">
<defs><linearGradient id="__U__-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>
<rect width="200" height="200" fill="url(#__U__-bg)"/>
<circle cx="164" cy="34" r="62" fill="#fff" opacity=".12"/>
<text x="100" y="100" dy=".35em" text-anchor="middle" font-size="84" font-weight="700" fill="#fff" font-family="-apple-system,Segoe UI,Tahoma,sans-serif">__INITIAL__</text>
</svg>"""

# The page with no personas: a cloud on the brand gradient.
_CLOUD = """<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="__LABEL__">
<defs><linearGradient id="__U__-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset=".55" stop-color="#6366f1"/><stop offset="1" stop-color="#c026d3"/></linearGradient></defs>
<rect width="200" height="200" fill="url(#__U__-bg)"/>
<circle cx="164" cy="34" r="62" fill="#fff" opacity=".12"/>
<path d="M62 132a26 26 0 0 1 2-52 36 36 0 0 1 68-6 28 28 0 0 1 8 58z" fill="#fff" opacity=".95"/>
<path d="M82 112h8M96 104v16M110 98v28M124 106v12" stroke="#6366f1" stroke-width="6" stroke-linecap="round"/>
</svg>"""


def _kind(persona: Mapping[str, Any]) -> str:
    voices = set((persona.get("voices") or {}).values())
    if voices & VOICETUT_FEMALE:
        return "woman"
    if voices & VOICETUT_MALE:
        return "man"
    return "initial"


def portrait(persona: Mapping[str, Any] | None, uid: str, label: str) -> str:
    if persona is None:
        svg = _CLOUD
    else:
        svg = {"woman": _WOMAN, "man": _MAN}.get(_kind(persona), _INITIAL)
    initial = (label.strip()[:1] or "?").upper()
    return (
        svg.replace("__U__", escape(uid, quote=True))
        .replace("__LABEL__", escape(label, quote=True))
        .replace("__INITIAL__", escape(initial))
    )
