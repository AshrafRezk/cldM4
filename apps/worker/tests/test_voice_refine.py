"""Hybrid recognition: the live model talks, the accurate one decides what Salesforce gets."""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app import main
from app.voice import refine as refine_mod
from app.voice.engine import VoiceEngine, refinable_answers, validate_script
from app.voice.refine import Refiner
from app.voice.store import VoiceStore

FAKE_HELPER = """
import json, sys
for job in json.load(open(sys.argv[3])):
    print(json.dumps({"id": job["id"], "text": "أشرف رزق"}, ensure_ascii=False), flush=True)
"""
CRASHING_HELPER = "import sys; sys.exit(3)"


def intake():
    return validate_script({
        "id": "rf-" + uuid.uuid4().hex[:6],
        "languages": ["ar-EG"],
        "steps": [
            {"key": "menu", "gather": True, "say": "جديد ولا متابعة؟", "next": "name",
             "routes": [{"when": ["جديد"], "next": "name", "value": "new"}]},
            {"key": "name", "gather": True, "say": "اسمك إيه؟", "next": "mobile"},
            {"key": "mobile", "gather": True, "confirm": True, "say": "رقمك إيه؟", "next": None},
        ],
        "commit": {"records": [{"sobject": "Contact", "fields": {"LastName": "{{name}}", "MobilePhone": "{{mobile}}"}}]},
    })


def finished_call(engine):
    script = intake()
    engine.store.upsert_script("t1", script)
    call = "WB" + uuid.uuid4().hex
    engine.start_call(tenant_id="t1", script_id=script["id"], call_sid=call, from_label="web", language="ar-EG")
    for text in ["جديد", "أشرف ورزقون", "01228566410", "أيوه"]:
        s = engine.store.session_by_call(call)
        engine.on_gather(call_sid=call, step=s["current_step"], attempt=s["attempt"], speech=text, turn=s["turn"])
    return engine.store.session_by_call(call)


@pytest.fixture()
def engine(tmp_path):
    return VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7, refine=True)


def refiner(tmp_path, engine, helper_source, monkeypatch):
    model = tmp_path / "model"
    model.mkdir(exist_ok=True)
    (model / "model.bin").write_text("")
    helper = tmp_path / "helper.py"
    helper.write_text(helper_source)
    monkeypatch.setattr(refine_mod, "HELPER", helper)
    settings = dataclasses.replace(main.settings, voice_refine_model=str(model), voicetut_python=sys.executable,
                                   voice_refine_dir=str(tmp_path / "refine"))
    return Refiner(settings, engine)


def spoken_audio(tmp_path) -> bytes:
    wav = tmp_path / "said.wav"
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=1", "-ar", "16000", "-ac", "1", str(wav)], check=True)
    return wav.read_bytes()


def test_only_the_callers_own_words_are_heard_again(engine):
    session = finished_call(engine)
    assert session["status"] == "refining", "Salesforce must not collect the live guess"
    assert refinable_answers(session["definition"], session["answers"]) == ["name"], \
        "a menu choice already routed and a read-back number was confirmed by the caller"


def test_without_the_accurate_model_calls_are_ready_at_once(tmp_path):
    plain = VoiceEngine(VoiceStore(str(tmp_path / "p.db")), public_base_url="https://api.test", ttl_days=7)
    assert finished_call(plain)["status"] == "ready_to_commit"


needs_ffmpeg = pytest.mark.skipif(not Path(main.settings.ffmpeg_bin).exists(), reason="needs ffmpeg")


@needs_ffmpeg
async def test_the_crm_gets_what_the_accurate_model_heard(tmp_path, engine, monkeypatch):
    r = refiner(tmp_path, engine, FAKE_HELPER, monkeypatch)
    session = finished_call(engine)
    r.keep(session, "name", spoken_audio(tmp_path), "أشرف ورزقون")
    assert await r.refine_waiting() == 1
    done = engine.store.session_by_call(session["call_sid"])
    assert done["status"] == "ready_to_commit"
    assert done["answers"]["name"] == "أشرف رزق"
    assert done["answers"]["mobile"] == "01228566410", "the confirmed number is untouched"
    assert done["commit_doc"]["records"][0]["fields"]["LastName"] == "أشرف رزق"
    caller = [t for t in done["turns"] if t.get("live")]
    assert caller == [{"role": "caller", "text": "أشرف رزق", "live": "أشرف ورزقون"}]
    assert not (tmp_path / "refine" / session["id"]).exists(), "the audio is gone once the call is released"


@needs_ffmpeg
async def test_a_failed_refine_releases_the_live_answers(tmp_path, engine, monkeypatch):
    r = refiner(tmp_path, engine, CRASHING_HELPER, monkeypatch)
    session = finished_call(engine)
    r.keep(session, "name", spoken_audio(tmp_path), "أشرف ورزقون")
    await r.refine_waiting()
    done = engine.store.session_by_call(session["call_sid"])
    assert done["status"] == "ready_to_commit"
    assert done["answers"]["name"] == "أشرف ورزقون"


async def test_no_kept_audio_releases_at_once(tmp_path, engine, monkeypatch):
    r = refiner(tmp_path, engine, FAKE_HELPER, monkeypatch)
    session = finished_call(engine)
    await r.refine_waiting()
    assert engine.store.session_by_call(session["call_sid"])["status"] == "ready_to_commit"
