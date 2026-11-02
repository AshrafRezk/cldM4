"""Scripted phone intake (docs/claude-code-handoff.md).

Twilio does the speech recognition; this package is a deterministic step
machine plus a CRM commit document. Nothing here may call Ollama, mflux, or
Whisper: a phone call must never take the Metal slot from chat.
"""
