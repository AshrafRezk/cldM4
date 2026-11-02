# Salesforce metadata — Cloudiator voice

Step-by-step developer setup: [docs/salesforce-voice-setup.md](../../docs/salesforce-voice-setup.md).

Metadata API format. Operator runbook and script format: [docs/voice.md](../../docs/voice.md).

| File | What |
| --- | --- |
| `objects/Cloudiator_Voice_Script__c.object` | Script record: `Definition__c` (script JSON), `External_Id__c` (script id, unique), `Inbound_Numbers__c` (comma-separated E.164), `Active__c`, plus `Published_Version__c` / `Last_Publish_Error__c` written back by Publish |
| `objects/Cloudiator_Voice_Question__c.object` | One question per record (master-detail to the script): Order, Arabic/English text, Target Field, Required, Attempts |
| `classes/CloudiatorVoice.cls` | callout helper: `callout:Cloudiator`, `setTimeout(120000)`, OpenAI-shaped error → exception with `X-Request-Id` |
| `classes/CloudiatorVoicePublish.cls` | Invocable **Publish Cloudiator voice script** (record Ids, max 10). With questions, builds the script from them and writes it to `Definition__c`; without, sends `Definition__c` with `External_Id__c`, `Inbound_Numbers__c`, `Active__c` overriding. Then queues the recording upload |
| `classes/CloudiatorVoiceScriptBuilder.cls` | Script + Questions → script JSON: greeting, questions, closing; answers, fixed values, transcript, and record links → commit records, parents first |
| `classes/CloudiatorVoiceRecordings.cls` | Queueable: Files titled `ar-EG`/`en-US` on a question, or `greeting.ar-EG`/`goodbye.en-US` on the script, are uploaded as that line's recording |
| `classes/CloudiatorVoiceTemplates.cls` | Invocable **Create Cloudiator voice script from template**: `case_intake`, `patient_support`, `customer_onboarding`, in Egyptian Arabic and English |
| `classes/CloudiatorVoiceCommit.cls` | Invocable **Commit Cloudiator voice sessions**. Blank session id = every `ready_to_commit` session (max 10). Inserts `commit_json` records in order, resolving `{{Lead.Id}}`-style placeholders, then enqueues the ack |
| `classes/CloudiatorVoiceCommitJob.cls` | Schedules the commit every 15 minutes: `CloudiatorVoiceCommitJob.scheduleEvery15Minutes();` |
| `pages/CloudiatorCall.page`, `labels/CustomLabels.labels` | Visualforce call button; set the `Cloudiator_Call_Link` label to your call link |
| `classes/CloudiatorVoiceTest.cls` | mock-callout tests (`CloudiatorVoiceCommitJobTest.cls` for the job) |
| `permissionsets/Cloudiator_Voice.permissionset` | object/field access for scripts and questions + the Publish, Commit, and Templates actions |

## Deploy

```bash
sf project deploy start --metadata-dir salesforce/voice --target-org <sandbox-alias> \
  --test-level RunSpecifiedTests --tests CloudiatorVoiceTest CloudiatorVoiceCommitJobTest
```

Then:

1. The Named Credential **`Cloudiator`** must already exist ([docs/salesforce.md](../../docs/salesforce.md) "Named Credential"), with a key that has the `voice` capability.
2. Assign **Cloudiator Voice** *and* the permission set that grants the External Credential **principal** to whoever runs Publish/Commit. Missing principal access shows up as a 401 even though the key works in curl.
3. Create a `Cloudiator Voice Script` record, paste the script JSON into Definition, set Script Id and Inbound Numbers, and run the Publish action (Flow, or a quick action backed by a screen flow).
4. Run Commit from a scheduled flow (e.g. every 5 minutes) or after a platform event. Each run is one list callout, the inserts, and one queued ack job.

## Why it is shaped this way

- **Callouts before DML.** Apex refuses a callout after uncommitted DML. Publish updates the script records only after all callouts. Commit fetches first, inserts, then acks from a `Queueable` with `Database.AllowsCallouts`.
- **USER_MODE inserts.** CRUD and FLS of the running user apply. Only sObjects named in the session's own `commit.records` are created; an unknown sObject or field fails that session and rolls it back, other sessions in the run still commit.
- **Type coercion.** Commit values arrive as text. Boolean, number, currency, percent, date, and datetime fields are converted; text is truncated to the field length; blank becomes null.
- **If an ack fails** (Mini down), the records exist but the session stays `ready_to_commit`, and the next Commit run would insert them again. Check the queued job's status before re-running, or have the flow commit by session id.

## Not yet verified

These classes have not been compiled in an org. Deploy to a sandbox first and expect to fix small compile issues.
