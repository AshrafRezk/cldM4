# Salesforce Apex examples (Phase F)

Prefer the installable unmanaged app in [`salesforce/`](../../salesforce/) (Setup UI, Flow actions, call logs). These standalone classes remain for Named Credential–only smoke tests.

Copy into a Developer Edition or sandbox after Named Credential `Cloudiator` and the External Credential principal permission set are in place. Full runbook: [docs/salesforce-app.md](../../docs/salesforce-app.md), [docs/salesforce.md](../../docs/salesforce.md), [docs/finish-v1-mini.md](../../docs/finish-v1-mini.md).

| File | Purpose |
| --- | --- |
| `CloudiatorChatCallout.cls` | Sync chat with `setTimeout(120000)`, `stream: false` |
| `CloudiatorJobPoller.cls` | Pattern A — Queueable poll, one callout per transaction |

Do not hardcode `sk-cld-` keys. Use `callout:Cloudiator/...` only.
