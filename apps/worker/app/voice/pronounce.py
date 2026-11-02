"""How a line is spoken, not how it is shown.

VoiceTut guesses vowels from bare Arabic text and keeps any harakat it is
given, so a misread word is fixed by writing its harakat. The caller's page
shows the script text unchanged; only the text sent to the voice (and so the
rendered clip's cache key) carries them.

Words come from two places, the script's own `pronunciations` winning:

* BUILTIN: words VoiceTut misread on real scripts, found by the round trip
  (render a line, transcribe it, see which words do not come back).
* script["pronunciations"]: {"word": "vowelled word"}, set by the script owner
  (Salesforce: the Pronunciations field), e.g. a company or drug name.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

MARKS = re.compile(r"[ً-ْٰ]")
WORD = re.compile(r"[ء-يًٰ-ْ]+")
# Clitics written onto a word: "وشكراً", "بالكامل", "للمرضى", "فبرنامج".
PREFIXES = ("وال", "بال", "فال", "كال", "لل", "و", "ب", "ف", "ل", "ك")

# Only words the round trip showed a clear gain on: "ميرك" came back as
# "مركز"/"مرك" in 3 of 3 bare renders and as "ميرك" in 3 of 3 vowelled ones.
# Harakat on "دعم" made it worse, so words go in here on evidence, not taste.
BUILTIN: dict[str, str] = {
    "ميرك": "مِيرْك",
    "مريم": "مَرْيَم",
}


def strip_marks(text: str) -> str:
    return MARKS.sub("", text)


def lexicon(script: Mapping[str, Any] | None) -> dict[str, str]:
    words = dict(BUILTIN)
    words.update((script or {}).get("pronunciations") or {})
    return words


def spoken(text: str, language: str, script: Mapping[str, Any] | None = None) -> str:
    """The line with harakat on every known word. English lines pass through."""
    if not language.lower().startswith("ar") or not text:
        return text
    words = lexicon(script)

    def fix(match: re.Match) -> str:
        word = match.group(0)
        if MARKS.search(word):
            return word  # the author already wrote harakat: theirs win
        if word in words:
            return words[word]
        for prefix in PREFIXES:
            rest = word[len(prefix):]
            if word.startswith(prefix) and len(rest) > 1 and rest in words:
                return prefix + words[rest]
            # "المرضى" is listed with its article; "للمرضى" drops the alef.
            if prefix == "لل" and word.startswith(prefix) and "ال" + rest in words:
                return "لل" + words["ال" + rest][2:]
        return word

    return WORD.sub(fix, text)
