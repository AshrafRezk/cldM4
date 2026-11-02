"""Render a script's `commit.records` into a CRM commit document. No network.

Substitution is a single regex pass, so a caller who says "{{ask_phone}}" gets
those literal characters in the Lead, not another answer.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.Id)?)\s*\}\}")
PARENT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.Id$")
# Salesforce Long Text Area tops out at 131072; most fields far below. Apex
# truncates per field; this only stops one runaway transcript filling the heap.
MAX_FIELD_CHARS = 32768


def render_value(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if PARENT_ID.match(name):
            # Resolved by Apex after the parent insert (`after` ordering).
            return "{{" + name + "}}"
        return values.get(name, "")

    return PLACEHOLDER.sub(replace, template)[:MAX_FIELD_CHARS]


def render_commit(
    commit: Mapping[str, Any],
    *,
    answers: Mapping[str, str],
    transcript: str,
    call: Mapping[str, str],
) -> dict[str, Any]:
    values = {**call, **{key: (value or "").strip() for key, value in answers.items()}}
    values["transcript"] = transcript
    records = []
    for record in commit.get("records") or []:
        rendered = copy.deepcopy(dict(record))
        rendered["fields"] = {
            name: render_value(template, values)
            for name, template in (record.get("fields") or {}).items()
        }
        rendered.setdefault("after", [])
        records.append(rendered)
    return {"records": records}


def transcript_text(turns: list[Mapping[str, str]]) -> str:
    labels = {"agent": "Agent", "caller": "Caller"}
    return "\n".join(f"{labels.get(t['role'], t['role'])}: {t['text']}" for t in turns)
