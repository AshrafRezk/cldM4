# Cloudiator Voice for Salesforce: developer setup

Step-by-step setup for the Salesforce developer: connect the org to Cloudiator, deploy the voice package, own a patient-support call script in Salesforce, put a call button on a Visualforce page, and write finished calls into Contacts and Cases.

Placeholders used below: Script Id **`client-psp`**, company **Your Company**. Use your own values.

| | |
| --- | --- |
| API | `https://api.cloudiator.org` |
| Package | `salesforce/voice/` (Metadata API format) |
| Example script | [`docs/examples/patient-support-script.json`](examples/patient-support-script.json) |
| Script format and options | [`configuring-voice.md`](configuring-voice.md), [`voice.md`](voice.md) |

> **You receive separately, privately:** the Cloudiator API key (`sk-cld-…`, minted with the `voice_intake` preset: chat + voice) and, once a script is published, its call link (`https://api.cloudiator.org/v1/voice/web/cl_…`). Never commit either, never hard-code them in Apex, never paste them into a ticket.

---

## 0. What the package contains

| Component | Purpose |
| --- | --- |
| `Cloudiator_Voice_Script__c` | One call flow: languages, greeting, closing, variables, personas, CRM mapping, beep, hold music |
| `Cloudiator_Voice_Question__c` | Child of the script: one question each, mapped to a field; optional read-back, routes, announcements |
| `Cloudiator_Voice_FAQ__c` | Child of the script: pre-written answers for questions callers ask mid-call |
| `CloudiatorVoicePublish` | Invocable **Publish Cloudiator voice script** |
| `CloudiatorVoiceCommit` | Invocable **Commit Cloudiator voice sessions**: creates records from finished calls and acks them |
| `CloudiatorVoiceCommitJob` | Schedules the commit every 15 minutes |
| `CloudiatorVoiceTemplates` | Invocable **Create Cloudiator voice script from template** (`case_intake`, `patient_support`, `customer_onboarding`) |
| `CloudiatorVoiceScriptBuilder`, `CloudiatorVoiceRecordings`, `CloudiatorVoice` | Builds the script JSON, uploads staff recordings, callout helper |
| `CloudiatorVoiceTest`, `CloudiatorVoiceCommitJobTest` | Tests with mocked callouts |
| `CloudiatorCall` (Visualforce) + `Cloudiator_Call_Link` (Custom Label) | Call button page |
| `Cloudiator_Voice` (permission set) | Object/field access, the actions, the page |

The Apex has unit tests with mocked callouts. **Deploy to a sandbox first.**

---

## 1. Let Apex reach Cloudiator

Confirm the API answers Salesforce-style requests with JSON, not an HTML challenge page:

```bash
curl -s -A 'Salesforce/1.0' https://api.cloudiator.org/v1/health
```

Expect `{"ok":true,...}`.

### 1a. External Credential

1. Setup → **Named Credentials** → **External Credentials** tab → **New**.
2. Label and Name `Cloudiator`, Authentication Protocol **Custom**. Save.
3. **Principals** → **New**: Parameter Name `CloudiatorPrincipal`, Identity Type **Named Principal**. Add an authentication parameter: Name `ApiKey`, Value = the Cloudiator API key. Save.
4. **Custom Headers** → **New**: Name `Authorization`, Value:

```
Bearer {!$Credential.CloudiatorPrincipal.ApiKey}
```

### 1b. Named Credential

1. Named Credentials tab → **New**. Label and Name: `Cloudiator` (exactly; the Apex calls `callout:Cloudiator`).
2. URL: `https://api.cloudiator.org` with no trailing slash.
3. External Credential: `Cloudiator`. Tick **Allow Formulas in HTTP Header**. Leave **Generate Authorization Header** unticked (the custom header does it). Save.

### 1c. Principal access (the step that is always missed)

1. Setup → Permission Sets → **New**: Label `Cloudiator API Access`.
2. **External Credential Principal Access** → Edit → add `Cloudiator - CloudiatorPrincipal`. Save.
3. Assign it to every user who publishes scripts and to the user who schedules the commit job (stage 6).

> **If skipped:** callouts return `401` even though the same key works with curl.

Remote Site Settings are not needed with a Named Credential.

---

## 2. Deploy the voice package

```bash
sf org login web --alias my-sandbox
```

```bash
sf project deploy start --metadata-dir salesforce/voice --target-org my-sandbox --test-level RunSpecifiedTests --tests CloudiatorVoiceTest CloudiatorVoiceCommitJobTest
```

Assign the **Cloudiator Voice** permission set to the admins who edit and publish scripts.

Smoke test (Developer Console → Debug → Open Execute Anonymous Window):

```apex
Object scripts = CloudiatorVoice.send('GET', '/v1/voice/scripts', null);
System.debug(JSON.serializePretty(scripts));
```

The debug log lists the scripts published for your key. `401` means stage 1c; an HTML body means a Cloudflare challenge.

---

## 3. Create the script in Salesforce

From the patient-support template (creates a Contact and a Case linked to it):

```apex
Id scriptId = CloudiatorVoiceTemplates.createOne('patient_support', 'Patient Support', 'client-psp');
System.debug(scriptId);
```

If a starter script was already published to Cloudiator under a Script Id, reuse that Script Id here: publishing from Salesforce replaces its content and **the existing call link keeps working**.

Open the new **Cloudiator Voice Script** record and set:

| Field | Value |
| --- | --- |
| Languages | `ar-EG;en-US` |
| Variables | `company = Your Company`<br>`company.ar = اسم الشركة`<br>`program = <official program name>`<br>`program.ar = <الاسم بالعربي>` |
| Personas | `Mariam \| مريم \| Mariam`<br>`Ahmed \| أحمد \| Ahmed` |
| Arabic Greeting | `أهلاً بيك، معاك {{agent}} من {{company}}. أهلاً بيك في {{program}}. المكالمة دي متسجلة، وبياناتك هتفضل سرية.` |
| English Greeting | `Hello, this is {{agent}} from {{company}}. Welcome to {{program}}. This call is recorded and your information is kept confidential.` |
| Beep Before Answer, Hold Music | ticked (defaults) |
| Transcript Field | `Case.Description` |
| Record Links | `Case.ContactId=Contact` |
| Fixed Values | `Case.Origin=Phone`<br>`Case.Status=New`<br>`Case.Subject={{program}} call` |

`{{agent}}` is the persona the caller picked; `{{company}}` and `{{program}}` come from Variables (CRM fields get the English value). A misspelled variable is rejected at publish.

### Questions (related list)

The template creates four (full name, mobile, treatment, symptoms). Fields: Order, Answer Key, Arabic Text, English Text, Target Field, Required, Attempts, Read Back, Next, Routes, Announcement.

- **Read Back** (ticked on the mobile question): the agent reads the digits back, "قلت 0 1 0 1…، صح كده؟", and a "no" asks again. Tick it for any number (case or prescription number).
- **Target Field** is `Object.Field`, e.g. `Contact.MobilePhone`. Blank keeps the answer in the transcript only.
- **Routes** (optional), one per line: `keywords => next answer key [= stored value]`, e.g. `new, جديد, نيو => full_name = New`.

### FAQs (related list)

When a caller asks something mid-call, the agent answers from these, in the persona's voice, then repeats its question. Add only answers approved by the client's medical and pharmacovigilance team.

| Field | Example |
| --- | --- |
| Keywords | `hours, open, مواعيد, بتقفلوا` |
| Arabic Answer | `{{company}} متاحين من ٩ الصبح لـ ٥ المسا.` |
| English Answer | `{{company}} is available 9 am to 5 pm.` |

---

## 4. Publish

```apex
List<CloudiatorVoicePublish.Result> r = CloudiatorVoicePublish.publish(
    new List<Id>{ [SELECT Id FROM Cloudiator_Voice_Script__c WHERE External_Id__c = 'client-psp' LIMIT 1].Id });
System.debug(JSON.serializePretty(r));
```

- Success: `version` is set and `Published_Version__c` updates; `Definition__c` shows exactly what was sent.
- Failure: `error` in the result and `Last_Publish_Error__c` on the record (e.g. missing Arabic text, a bad `Object.Field`).
- New or changed lines are voiced on the appliance in the background (about 20 seconds per line). The call page shows "تحضير صوت مريم… 7/22 · Preparing Mariam's voice… 7/22" until a voice is ready.
- Optional staff recordings: attach an audio File to a Question titled `ar-EG` or `en-US` (or to the Script titled `greeting.ar-EG`, `goodbye.en-US`) and publish again. Recordings replace the generated voice.

For admins, add a Screen Flow or quick action on the Voice Script page that calls **Publish Cloudiator voice script** with the record Id.

The call link for a published script is minted with the Cloudiator key (it is shown once):

```bash
curl -s -X POST https://api.cloudiator.org/v1/voice/scripts/client-psp/web-link -H "Authorization: Bearer $CLOUDIATOR_KEY"
```

---

## 5. Visualforce call button

1. Setup → **Custom Labels** → `Cloudiator_Call_Link` (deployed with a placeholder) → edit the value to the call link.
2. The page **CloudiatorCall** (deployed) shows a bilingual "اتصل بينا · Call us" button that opens the call in a new tab. Use it from a Visualforce tab, a page layout section, or an Experience Cloud / Salesforce Site page (grant the page to the site's guest profile if patients use it unauthenticated).

> **Open in a new tab, do not iframe.** The call page needs the microphone and sends `Permissions-Policy: microphone=(self)`, so a browser blocks the microphone inside a Visualforce iframe. Embedding needs a change on the Cloudiator side first.

---

## 6. Write finished calls into Contacts and Cases

As a user with **Cloudiator API Access** (stage 1c) and create rights on Contact and Case:

```apex
CloudiatorVoiceCommitJob.scheduleEvery15Minutes();
```

Each run lists finished calls (up to 10), inserts the Contact, then the Case with `ContactId` set, using that user's permissions (USER_MODE), then acks each call to Cloudiator so it is not inserted twice. Remove the schedule with Setup → Scheduled Jobs (`Cloudiator voice commit :0/15/30/45`).

Low-volume alternative without code: Setup → Flows → New → **Schedule-Triggered Flow**, Frequency **Daily**, one **Action** element → **Commit Cloudiator voice sessions** with `sessionId` left empty.

---

## 7. Test end to end

1. Open the CloudiatorCall page, press **Call us**, pick a persona and "اتصل بالعربي", allow the microphone.
2. Answer the questions; at the mobile question the agent reads the digits back; answer "أيوه".
3. Check the call is waiting:

```apex
Object ready = CloudiatorVoice.send('GET', '/v1/voice/sessions?status=ready_to_commit', null);
System.debug(JSON.serializePretty(ready));
```

4. Commit once by hand:

```apex
System.debug(JSON.serializePretty(
    CloudiatorVoiceCommit.commitSessions(new List<CloudiatorVoiceCommit.Request>{ new CloudiatorVoiceCommit.Request() })));
```

5. Confirm a new Contact (name, mobile) and a Case linked to it (Origin Phone, Status New, Subject, transcript in Description). After the queued ack job runs, the session shows `committed`.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `401` from Apex, curl works | Principal access missing (1c), or the custom header formula is wrong |
| JSON parse error, body starts with `<!DOCTYPE html` | Cloudflare challenged the callout; check Security Level and Browser Integrity Check for `api.cloudiator.org` |
| `403 scope_denied` | The key lacks the `voice` capability; ask for a `voice_intake` key |
| Publish error "needs Arabic text" | Every greeting, closing, question and FAQ needs both texts when Languages lists both |
| Publish error "must look like Object.Field" | Target Field, Transcript Field, Fixed Values and Record Links use API names, e.g. `Case.Subject` |
| Call button shows "Preparing voice… n/22" | Normal for a few minutes after a publish |
| Commit inserted nothing | No calls finished yet, or the running user cannot create Contact/Case (debug log shows the USER_MODE error) |
| "You have uncommitted work pending" | Call the actions from a fresh transaction (Flow action, Queueable), not after DML in the same one |

---

## 9. Before real patients

- Program name, greeting wording and every FAQ answer approved by the client's medical / pharmacovigilance team.
- Adverse events: the symptoms answer lands in the Case description only. Define how it reaches the safety team (Case record type, queue, or a Flow on new Cases).
- Retention: transcripts and answers stay on the Cloudiator appliance for 7 days after the Salesforce ack; callers' voices never leave it.
- One call at a time on the appliance; further callers wait in line with hold music.
