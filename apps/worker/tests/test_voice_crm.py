from app.voice.crm import MAX_FIELD_CHARS, render_commit, render_value, transcript_text


def test_step_answers_and_transcript_substitute():
    commit = {
        "records": [
            {"sobject": "Lead", "fields": {"LastName": "{{ask_name}}", "Description": "{{transcript}}"}}
        ]
    }
    out = render_commit(
        commit, answers={"ask_name": "  أحمد علي "}, transcript="Agent: hi", call={"from": "+20"}
    )
    fields = out["records"][0]["fields"]
    assert fields == {"LastName": "أحمد علي", "Description": "Agent: hi"}
    assert out["records"][0]["after"] == []


def test_parent_id_placeholders_are_left_for_apex():
    assert render_value("{{Lead.Id}}", {}) == "{{Lead.Id}}"
    assert render_value("{{ Account.Id }}", {}) == "{{Account.Id}}"


def test_unknown_and_missing_keys_are_empty():
    assert render_value("[{{nope}}]", {}) == "[]"


def test_caller_text_is_not_re_expanded():
    values = {"ask_reason": "{{ask_phone}}", "ask_phone": "+2010"}
    assert render_value("{{ask_reason}}", values) == "{{ask_phone}}"


def test_builtins_from_call():
    out = render_commit(
        {"records": [{"sobject": "Task", "fields": {"Subject": "Call from {{from}}"}}]},
        answers={},
        transcript="",
        call={"from": "+201234", "to": "+20999", "call_sid": "CA1"},
    )
    assert out["records"][0]["fields"]["Subject"] == "Call from +201234"


def test_runaway_values_are_capped():
    assert len(render_value("{{t}}", {"t": "x" * (MAX_FIELD_CHARS + 10)})) == MAX_FIELD_CHARS


def test_transcript_text_labels_turns():
    turns = [{"role": "agent", "text": "Name?"}, {"role": "caller", "text": "Sara"}]
    assert transcript_text(turns) == "Agent: Name?\nCaller: Sara"
