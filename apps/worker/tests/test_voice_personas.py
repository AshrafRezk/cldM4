"""Callers pick who they talk to ("Hello, this is Mariam from Acme"), and hear a beep before answering."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from app import main
from app.voice import speech
from app.voice.audio import script_lines
from app.voice.engine import ScriptInvalid, VoiceEngine, validate_script
from app.voice.store import VoiceStore

HAS_FFMPEG = bool(shutil.which("ffmpeg") or os.path.exists("/opt/homebrew/bin/ffmpeg"))


def acme(**overrides):
    script = {
        "id": "acme-" + uuid.uuid4().hex[:6],
        "languages": ["ar-EG", "en-US"],
        "variables": {"company": {"ar-EG": "أكمي", "en-US": "Acme"}},
        "personas": [
            {"id": "mariam", "name": {"ar-EG": "مريم", "en-US": "Mariam"}, "voice": "Mariam"},
            {"id": "ahmed", "name": {"ar-EG": "أحمد", "en-US": "Ahmed"},
             "voice": {"ar-EG": "Ahmed", "en-US": "Karim"}},
        ],
        "steps": [
            {"key": "greeting", "next": "ask_name",
             "say": {"ar-EG": "أهلاً، معاك {{agent}} من {{company}}.", "en-US": "Hello, this is {{agent}} from {{company}}."}},
            {"key": "ask_name", "gather": True, "next": "goodbye",
             "say": {"ar-EG": "ممكن اسمك بعد الصافرة؟", "en-US": "Your name after the beep, please?"}},
            {"key": "goodbye", "say": {"ar-EG": "مع السلامة.", "en-US": "Goodbye."}},
        ],
        "commit": {"records": [{"sobject": "Case", "fields": {
            "SuppliedName": "{{ask_name}}", "Subject": "Voice call with {{agent}} ({{company}})"}}]},
    }
    script.update(overrides)
    return script


def test_personas_validate_and_agent_waits_for_the_caller():
    clean = validate_script(acme())
    assert [p["id"] for p in clean["personas"]] == ["mariam", "ahmed"]
    assert clean["personas"][0]["voices"] == {"ar-EG": "Mariam", "en-US": "Mariam"}
    assert clean["steps"][0]["say"]["en-US"] == "Hello, this is {{agent}} from Acme."
    assert clean["beep"] is True


@pytest.mark.parametrize("bad", [
    lambda s: s.pop("personas"),  # {{agent}} without personas is a typo
    lambda s: s["personas"].append({"id": "mariam", "name": "x", "voice": "Hadeer"}),  # duplicate id
    lambda s: s["personas"][0].update(voice={"fr-FR": "Mariam"}),
    lambda s: s.update(variables={"agent": "x"}),  # reserved
])
def test_bad_personas_are_rejected(bad):
    script = acme()
    bad(script)
    with pytest.raises(ScriptInvalid):
        validate_script(script)


def test_each_persona_has_its_own_lines_and_voice():
    clean = validate_script(acme())
    lines = main.voice_audio.lines(clean)
    assert len(lines) == 2 * 2 * (3 + 3)
    greet = {(l["persona"], l["language"]): l for l in lines if l["key"] == "greeting"}
    assert greet[("mariam", "ar-EG")]["text"] == "أهلاً، معاك مريم من أكمي."
    assert greet[("ahmed", "en-US")]["text"] == "Hello, this is Ahmed from Acme."
    by_voice = {(l["persona"], l["language"]): l["speaker"] for l in script_lines(clean, lambda s, lang, p: (p or {}).get("voices", {}).get(lang))}
    assert by_voice[("ahmed", "en-US")] == "Karim" and by_voice[("mariam", "ar-EG")] == "Mariam"


def test_the_engine_speaks_as_the_chosen_persona(tmp_path):
    engine = VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7)
    script = acme()
    engine.store.upsert_script("t1", validate_script(script))
    call = "WB" + uuid.uuid4().hex
    reply = engine.start_call(tenant_id="t1", script_id=script["id"], call_sid=call,
                              from_label="web", language="en-US", persona="ahmed")
    assert reply["persona"] == "ahmed"
    assert reply["verbs"][0]["say"] == "Hello, this is Ahmed from Acme."
    assert reply["verbs"][1]["gather"]["beep"] is True
    session = engine.store.session_by_call(call)
    engine.on_gather(call_sid=call, step="ask_name", attempt=1, speech="Sara", turn=session["turn"])
    fields = engine.store.session_by_call(call)["commit_doc"]["records"][0]["fields"]
    assert fields["Subject"] == "Voice call with Ahmed (Acme)"

    default = engine.start_call(tenant_id="t1", script_id=script["id"], call_sid="WB" + uuid.uuid4().hex,
                                from_label="web", language="ar-EG")
    assert default["verbs"][0]["say"] == "أهلاً، معاك مريم من أكمي."
    with pytest.raises(ScriptInvalid):
        engine.start_call(tenant_id="t1", script_id=script["id"], call_sid="WB" + uuid.uuid4().hex,
                          from_label="web", language="ar-EG", persona="nobody")


def test_beep_can_be_turned_off(tmp_path):
    engine = VoiceEngine(VoiceStore(str(tmp_path / "v.db")), public_base_url="https://api.test", ttl_days=7)
    script = acme(beep=False)
    engine.store.upsert_script("t1", validate_script(script))
    reply = engine.start_call(tenant_id="t1", script_id=script["id"], call_sid="WB" + uuid.uuid4().hex,
                              from_label="web", language="en-US")
    assert reply["verbs"][1]["gather"]["beep"] is False


@pytest.fixture()
def fake_speech(monkeypatch):
    async def synthesize(text, **kwargs):
        return b"fallback-audio"

    async def transcribe(audio, *, language, settings, digits_hint=False):
        return "Sara" if audio else ""

    monkeypatch.setattr(speech, "synthesize", synthesize)
    monkeypatch.setattr(speech, "transcribe", transcribe)


async def links(make_client, headers, script):
    async with make_client(headers) as client:
        assert (await client.post("/v1/voice/scripts", json=script)).status_code == 200
        call = (await client.post(f"/v1/voice/scripts/{script['id']}/web-link")).json()["url"]
        studio = (await client.post(f"/v1/voice/scripts/{script['id']}/studio-link")).json()["url"]
    strip = lambda u: u.removeprefix("https://api.cloudiator.test")  # noqa: E731
    return strip(call), strip(studio)


async def test_caller_picks_a_persona_on_the_page(make_client, install_key, fake_speech):
    _r, headers = install_key(capabilities=["voice"])
    call, _studio = await links(make_client, headers, acme())
    async with make_client() as anon:
        page = (await anon.get(call)).text
        assert 'name="persona" value="mariam" checked' in page and "أحمد · Ahmed" in page
        turn = (await anon.post(f"{call}/start", params={"lang": "ar-EG", "persona": "ahmed"})).json()
        assert turn["persona"] == "ahmed"
        assert turn["clips"][0]["text"] == "أهلاً، معاك أحمد من أكمي."
        assert turn["listen"]["beep"] is True
        bad = await anon.post(f"{call}/start", params={"persona": "nobody"})
        assert bad.status_code == 400

        queued = (await anon.post(f"{call}/start", params={"lang": "en-US", "persona": "mariam"})).json()
        assert queued["queued"] is True
        assert queued["clips"][0]["text"] == (
            "Hi, this is Mariam from Acme. I'm just finishing a call and will be with you right away. "
            "Please don't hang up, and thank you for your patience!"
        )
        assert queued["music"] is True
        await anon.post(f"{call}/hangup", params={"call_id": turn["call_id"]})
        connected = (await anon.post(f"{call}/wait", params={"ticket": queued["ticket"]})).json()
        assert connected["persona"] == "mariam"
        assert connected["clips"][0]["text"] == "Hello, this is Mariam from Acme."


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
async def test_each_persona_records_their_own_lines(make_client, install_key, fake_speech, tmp_path):
    _r, headers = install_key(capabilities=["voice"])
    call, studio = await links(make_client, headers, acme())
    wav = tmp_path / "take.wav"
    subprocess.run([main.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=330:duration=1", str(wav)], check=True)
    async with make_client() as anon:
        data = (await anon.get(f"{studio}/lines")).json()
        assert [p["id"] for p in data["personas"]] == ["mariam", "ahmed"]
        assert len(data["lines"]) == 24
        saved = await anon.put(f"{studio}/recordings/greeting/ar-EG", params={"persona": "mariam"},
                               content=wav.read_bytes())
        assert saved.status_code == 200, saved.text
        assert (await anon.get(f"{studio}/audio/greeting/ar-EG", params={"persona": "mariam"})).json()["source"] == "recording"
        assert (await anon.get(f"{studio}/audio/greeting/ar-EG", params={"persona": "ahmed"})).json()["source"] == "fallback"

        mariam = (await anon.post(f"{call}/start", params={"lang": "ar-EG", "persona": "mariam"})).json()
        assert mariam["clips"][0]["source"] == "recording"
        await anon.post(f"{call}/hangup", params={"call_id": mariam["call_id"]})
        ahmed = (await anon.post(f"{call}/start", params={"lang": "ar-EG", "persona": "ahmed"})).json()
        assert ahmed["clips"][0]["source"] == "fallback"


def test_hold_message_adapts_to_persona_and_company():
    from app.voice.engine import hold_text, speak

    full = validate_script(acme())
    ar = speak(hold_text(full, "ar-EG"), "ar-EG", full["personas"][1])
    assert ar.startswith("أهلاً بيك، معاك أحمد من أكمي.") and "متقفلش من فضلك" in ar
    no_company = validate_script(acme(variables={}, steps=[
        {"key": "q", "gather": True, "say": "Name?"}], commit={"records": []}))
    assert hold_text(no_company, "en-US").startswith("Hi, this is {{agent}}. I'm just finishing")
    plain = validate_script({"id": "p", "languages": ["en-US"], "variables": {"company": "Acme"},
                             "steps": [{"key": "q", "gather": True, "say": "Name?"}]})
    assert hold_text(plain, "en-US").startswith("Thanks for calling Acme. I'm just finishing")
    custom = validate_script({"id": "c", "languages": ["en-US"], "hold_say": "Please hold.",
                              "steps": [{"key": "q", "gather": True, "say": "Name?"}]})
    assert hold_text(custom, "en-US") == "Please hold."
    assert validate_script({"id": "m", "steps": [{"key": "q", "say": "x"}], "hold_music": False})["hold_music"] is False


async def test_fallback_keeps_each_persona_gender(make_client, install_key, monkeypatch):
    """Before natural clips exist: Ahmed must not sound like a woman, Mariam not like a man."""
    used = []

    async def synthesize(text, *, language, local_voice, cache_dir):
        used.append((language, local_voice))
        return b"fallback-audio"

    monkeypatch.setattr(speech, "synthesize", synthesize)
    _r, headers = install_key(capabilities=["voice"])
    script = acme()
    script["personas"][1]["voice"] = "Ahmed"  # male in both languages
    call, _studio = await links(make_client, headers, script)
    async with make_client() as anon:
        ahmed_en = (await anon.post(f"{call}/start", params={"lang": "en-US", "persona": "ahmed"})).json()
        await anon.post(f"{call}/hangup", params={"call_id": ahmed_en["call_id"]})
        mariam_ar = (await anon.post(f"{call}/start", params={"lang": "ar-EG", "persona": "mariam"})).json()
        await anon.post(f"{call}/hangup", params={"call_id": mariam_ar["call_id"]})
        ahmed_ar = (await anon.post(f"{call}/start", params={"lang": "ar-EG", "persona": "ahmed"})).json()
        mariam_en_voice = [v for lang, v in used if lang == "en-US"]
    assert set(mariam_en_voice) == {"Daniel"}, "English Ahmed uses the male fallback"
    assert [c["source"] for c in mariam_ar["clips"]] == ["pending", "pending"], "no female Arabic system voice: wait, never Majed"
    assert ("ar-EG", "Majed") in used and [c["source"] for c in ahmed_ar["clips"]] == ["fallback", "fallback"]


def test_renders_are_queued_in_call_order(monkeypatch, tmp_path):
    import dataclasses

    from app.voice.audio import VoiceAudio

    (tmp_path / "python").write_text("")
    audio = VoiceAudio(dataclasses.replace(main.settings, voice_tts_engine="voicetut",
                                           voicetut_python=str(tmp_path / "python"),
                                           voice_audio_dir=str(tmp_path / "audio")))
    monkeypatch.setattr(audio, "_ensure_worker", lambda: None)
    assert audio.schedule(validate_script(acme())) == 24
    batch = audio.queue.get_nowait()
    first = [(l["persona"], l["language"], l["key"]) for l in batch[:6]]
    assert first == [("mariam", "ar-EG", k) for k in ("greeting", "ask_name", "__hold__", "goodbye", "__fail__", "__offscript__")], \
        "one persona+language is finished before the next starts, in call order"
    assert {(l["persona"], l["language"]) for l in batch[6:12]} == {("mariam", "en-US")}
