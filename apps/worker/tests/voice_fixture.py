"""The Arabic intake script from docs/claude-code-handoff.md §4.1."""

from __future__ import annotations

import copy

INTAKE_AR = {
    "id": "intake-ar",
    "display_name": "Arabic inbound intake",
    "language": "ar-EG",
    "voice": "Polly.Zeina",
    "inbound_numbers": ["+201000000001"],
    "steps": [
        {
            "key": "greeting",
            "say": "مرحباً بك في كلاودياتور. سيتم تسجيل هذه المكالمة.",
            "gather": False,
            "next": "ask_name",
        },
        {
            "key": "ask_name",
            "say": "من فضلك قل اسمك الكامل بعد الصافرة.",
            "gather": True,
            "timeout": 5,
            "speech_timeout": "auto",
            "max_attempts": 2,
            "on_fail": "continue",
            "next": "ask_reason",
        },
        {
            "key": "ask_reason",
            "say": "ما سبب اتصالك اليوم؟",
            "gather": True,
            "max_attempts": 2,
            "on_fail": "continue",
            "next": "ask_phone",
        },
        {
            "key": "ask_phone",
            "say": "أكد رقم هاتفك للتواصل.",
            "gather": True,
            "max_attempts": 2,
            "on_fail": "continue",
            "next": "goodbye",
        },
        {
            "key": "goodbye",
            "say": "شكراً لك. سيتم تسجيل طلبك الآن.",
            "gather": False,
            "next": None,
        },
    ],
    "commit": {
        "records": [
            {
                "sobject": "Lead",
                "fields": {
                    "LastName": "{{ask_name}}",
                    "Company": "Phone Intake",
                    "Phone": "{{ask_phone}}",
                    "Description": "{{ask_reason}}\n\n---\n{{transcript}}",
                },
            },
            {
                "sobject": "Task",
                "fields": {
                    "Subject": "Inbound voice intake",
                    "Status": "Completed",
                    "Description": "{{transcript}}",
                    "WhoId": "{{Lead.Id}}",
                },
                "after": ["Lead"],
            },
        ]
    },
}


def intake(**overrides):
    script = copy.deepcopy(INTAKE_AR)
    script.update(overrides)
    return script


INTAKE_BILINGUAL = {
    "id": "case-intake",
    "display_name": "Case intake",
    "languages": ["ar-EG", "en-US"],
    "voices": {"ar-EG": "Hadeer", "en-US": "Hadeer"},
    "inbound_numbers": [],
    "steps": [
        {"key": "greeting", "gather": False, "next": "ask_name",
         "say": {"ar-EG": "أهلاً بيك في خدمة العملاء.", "en-US": "Welcome to customer care."}},
        {"key": "ask_name", "gather": True, "next": "ask_issue",
         "say": {"ar-EG": "ممكن تقولي اسمك بالكامل؟", "en-US": "May I have your full name?"}},
        {"key": "ask_issue", "gather": True, "next": "goodbye",
         "say": {"ar-EG": "قولي باختصار إيه المشكلة؟", "en-US": "Briefly, what is the problem?"}},
        {"key": "goodbye", "gather": False, "next": None,
         "say": {"ar-EG": "شكراً ليك، هنكلمك قريب.", "en-US": "Thank you, we will be in touch."}},
    ],
    "commit": {"records": [{"sobject": "Case", "fields": {
        "SuppliedName": "{{ask_name}}", "Subject": "{{ask_issue}}", "Origin": "Web", "Description": "{{transcript}}"}}]},
}


def bilingual(**overrides):
    script = copy.deepcopy(INTAKE_BILINGUAL)
    script.update(overrides)
    return script
