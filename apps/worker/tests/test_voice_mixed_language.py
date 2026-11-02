"""Egyptian callers mix Egyptian Arabic, English and French in one answer."""

from __future__ import annotations

import uuid

import pytest

from app import main
from app.voice import speech
from app.voice.engine import looks_like_question, match_faq, pick_route, validate_script


def test_whisper_hallucinations_are_silence():
    """Real calls on 2026-11-02: near-silent windows came back as subtitle credits."""
    assert speech.drop_hallucinations("ترجمة نانسي قنقر") == ""
    assert speech.drop_hallucinations("اشتركوا في القناة") == ""
    assert speech.drop_hallucinations("Thanks for watching!") == ""
    assert speech.drop_hallucinations("متابعة الحلقة ديما") == "متابعة الحلقة ديما"
    assert speech.drop_hallucinations("عايز ترجمة للروشتة") == "عايز ترجمة للروشتة"


def test_repeats_collapse_but_real_doubles_stay():
    assert speech.collapse_repeats("I don't get your question. I don't get your question.") == "I don't get your question."
    assert speech.collapse_repeats("أحمد علي أحمد علي") == "أحمد علي"
    assert speech.collapse_repeats("لأ لأ أنا نيوكيس") == "لأ لأ أنا نيوكيس"
    assert speech.collapse_repeats("01 01 23") == "01 01 23"


def script():
    return validate_script({
        "id": "mx", "languages": ["ar-EG", "en-US"],
        "steps": [{"key": "menu", "gather": True, "next": None, "say": {"ar-EG": "جديد ولا متابعة؟", "en-US": "New or existing?"},
                   "routes": [{"when": {"ar-EG": ["جديد"], "en-US": ["new"]}, "next": None, "value": "New"}]}],
        "faq": [{"key": "price", "when": {"ar-EG": ["سعر"], "en-US": ["price", "prix"]}, "say": "مجاناً"}],
    })


def test_an_english_or_french_word_counts_on_the_arabic_line():
    s = script()
    assert pick_route(s["steps"][0], "لا دي حالة new خالص", "ar-EG")["value"] == "New"
    assert match_faq(s, "هو le prix كام؟", "ar-EG") == "price"
    assert looks_like_question("what time do you close", "ar-EG")
    assert looks_like_question("هو الدوا ده بيتاخد إمتى", "en-US")
