# Salesforce Apex examples (Phase F)

Copy these into a Developer Edition or sandbox after Named Credential `Cloudiator` and the External Credential principal permission set are in place. Full runbook: [docs/salesforce.md](../../docs/salesforce.md) and [docs/finish-v1-mini.md](../../docs/finish-v1-mini.md).

| File | Purpose |
| --- | --- |
| `CloudiatorChatCallout.cls` | Sync chat with `setTimeout(120000)`, `stream: false` |
| `CloudiatorJobPoller.cls` | Pattern A — Queueable poll, one callout per transaction |

Do not hardcode `sk-cld-` keys. Use `callout:Cloudiator/...` only.
