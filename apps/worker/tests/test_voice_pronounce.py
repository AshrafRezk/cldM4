"""Harakat fix how a line is voiced without changing what the caller reads."""

from __future__ import annotations

import pytest

from app import main
from app.voice.engine import ScriptInvalid, validate_script
from app.voice.pronounce import spoken


def script(**extra):
    return validate_script({
        "id": "p1", "languages": ["ar-EG", "en-US"],
        "steps": [{"key": "hi", "say": {"ar-EG": "أهلاً بيك في برنامج دعم المرضى، معاك مريم من ميرك.",
                                        "en-US": "Hello from Merck."}}],
        **extra,
    })


def test_known_words_get_harakat_with_their_clitics():
    assert spoken("وميرك لمريم بالكامل", "ar-EG") == "ومِيرْك لمَرْيَم بالكامل"


def test_english_and_written_harakat_pass_through():
    assert spoken("Merck مريم", "en-US") == "Merck مريم"
    assert spoken("مَرْيَم", "ar-EG") == "مَرْيَم"


def test_the_script_owner_wins():
    s = script(pronunciations={"ميرك": "مِيرِك"})
    assert spoken("من ميرك", "ar-EG", s) == "من مِيرِك"


@pytest.mark.parametrize("bad", [{"ميرك": "مارك"}, {"two words": "x"}, ["x"], {"ميرك": 3}])
def test_a_pronunciation_may_only_add_harakat(bad):
    with pytest.raises(ScriptInvalid):
        script(pronunciations=bad)


def test_the_page_shows_the_text_and_the_voice_gets_the_harakat():
    lines = [l for l in main.voice_audio.lines(script()) if l["key"] == "hi"]
    ar = next(l for l in lines if l["language"] == "ar-EG")
    en = next(l for l in lines if l["language"] == "en-US")
    assert "ميرك" in ar["text"] and "مِيرْك" in ar["spoken"]
    assert en["spoken"] == en["text"]
    # A changed pronunciation is a different clip, so it is rendered again.
    other = next(l for l in main.voice_audio.lines(script(pronunciations={"ميرك": "مِيرِك"}))
                 if l["key"] == "hi" and l["language"] == "ar-EG")
    assert main.voice_audio.rendered_path(ar["speaker"], "ar-EG", ar["spoken"]) != \
        main.voice_audio.rendered_path(other["speaker"], "ar-EG", other["spoken"])
