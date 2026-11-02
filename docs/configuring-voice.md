# Configuring Cloudiator voice for a client

One Mini can answer for many companies and programs. Everything a caller hears and every record a call creates comes from a **script**, which you write in Salesforce (or send as JSON). Nothing is hard-coded on the Mini, and nothing is sent to a third party.

This guide is for the person setting up a new client: a pharma patient-support program, a case-management desk, or a call center onboarding customers.

## The pieces

| Piece | What it is | Example |
| --- | --- | --- |
| **Script** | One call flow for one client and purpose | "Acme Pharma, patient support" |
| **Languages** | The buttons callers choose from, in order | `ar-EG`, `en-US` |
| **Variables** | Names you write once and use everywhere as `{{name}}` | `company = Acme Pharma` |
| **Greeting / Closing** | Spoken first and last | "أهلاً، معاك {{company}}…" |
| **Questions** | Spoken, then the caller answers | "ممكن اسمك بالكامل؟" |
| **Announcements** | Spoken, no answer expected | "Our nurses are available 9 to 5." |
| **Routes** | Send the caller to a different next question depending on what they said | new patient vs existing case |
| **CRM mapping** | Which Salesforce field each answer fills, plus fixed values and links | `Contact.MobilePhone`, `Case.Origin=Phone` |
| **Personas** | Agents the caller can pick; `{{agent}}` is their name | Mariam, Ahmed |
| **FAQs** | Pre-written answers to questions callers ask mid-call; then back to the question | "Take it after a meal." |
| **Hold / no-answer lines** | Spoken while waiting in line (over hold music) / when someone never answers | built in, can be replaced |
| **Voice** | Generated on the Mini, or a person's recording from the studio | studio recording per line |
| **Call link** | The URL callers open | `https://api.cloudiator.org/v1/voice/web/cl_…` |

## The company name: variables

Write the client's name (and anything else that changes between clients) once, in **Variables**, and use `{{name}}` in any line or fixed value.

In Salesforce, on the Voice Script, the **Variables** field, one per line:

```
company = Acme Pharma
company.ar = أكمي فارما
program = Acme Care
program.ar = برنامج أكمي كير
```

- `name = value` applies to every language. `name.ar` / `name.en` override it for Arabic or English.
- Greeting: `أهلاً، معاك {{company}}. أهلاً بيك في {{program}}.` → *"أهلاً، معاك أكمي فارما. أهلاً بيك في برنامج أكمي كير."*
- English: `Hello, this is {{company}}. Welcome to {{program}}.` → *"Hello, this is Acme Pharma. Welcome to Acme Care."*
- In CRM fields (`Fixed Values`, e.g. `Case.Subject={{program}} call`) the **English** value is used.
- A misspelled `{{compnay}}` is refused when you publish, so callers never hear braces.

**Setting up the next client** is: clone the script, change the Variables (and Script Id), publish. Every line is re-voiced automatically.

## Personas: callers choose who they talk to

List the agents a script offers in **Personas** on the Voice Script, one per line: `English name | Arabic name | voice`, with an optional 4th column for a different English voice.

```
Mariam | مريم | Mariam
Ahmed | أحمد | Ahmed | Karim
```

- The call page shows **تحب تكلم مين؟ · Who would you like to talk to?** with one choice per persona (the first is selected), above the language buttons.
- Write `{{agent}}` in any line: `أهلاً، معاك {{agent}} من {{company}}.` → *"أهلاً، معاك مريم من أكمي فارما."* `{{agent}}` also works in Fixed Values (CRM gets the English name), e.g. `Case.Subject=Call with {{agent}}`.
- Each persona speaks in their own voice. Voice names are the Mini's speakers: female Hadeer, Hanan, Mariam, Rana, Sarah, Yasmin, Yara; male Ahmed, Ali, Hassan, Karim, Mahmoud, Mohammed, Mostafa, Ramy, Shaker, Tareq, Yehia, Youssef.
- In the recording studio, each persona has its own set of lines, so the real Mariam records Mariam's lines and the real Ahmed records Ahmed's.
- Up to 6 personas per script. Without personas, `{{agent}}` is refused at publish.

## Beep, and what callers hear while they wait

- **Beep Before Answer** (on by default): a short soft tone after each question, so "قولي اسمك بعد الصافرة / after the beep" is true. Untick it to turn it off.
- **Waiting in line.** The Mini takes one call at a time. Anyone else hears **Hold Music** (on by default; soft chords generated in the caller's browser, no music file, nothing fetched from anyone) and, every 30 seconds, the music dips and the agent says, in the caller's language:
  - *"أهلاً بيك، معاك مريم من أكمي فارما. أنا بخلّص مكالمة دلوقتي وهبدأ معاك على طول. متقفلش من فضلك، وشكراً على صبرك!"*
  - *"Hi, this is Mariam from Acme Pharma. I'm just finishing a call and will be with you right away. Please don't hang up, and thank you for your patience!"*
  
  The opening uses the persona they picked and the `company` variable when the script has them ("Thanks for calling Acme Pharma." without personas). The page also shows their place in line. A script can replace the whole message with `hold_say` (JSON). The hold line can be recorded in the studio like any other.

## When a caller asks something instead of answering

Callers ask things mid-call: "هو الدوا ده بيتاخد قبل الأكل؟", "when do you close?". The agent answers from **FAQs you write**, in its own voice, then goes straight back to the question it asked:

> *Caller:* هو أنا ممكن آخد الحباية وأنا جعان؟
> *Mariam:* الدوا ده بيتاخد بعد الأكل. نرجع لسؤالنا. ممكن تقولي اسمك بالكامل؟

Add **Cloudiator Voice FAQ** records under the Voice Script:

| Field | Meaning |
| --- | --- |
| Keywords | words a caller would use, comma separated, any language: `food, meal, أكل, جعان, قبل الأكل` |
| Arabic Answer / English Answer | the answer as spoken |
| FAQ Key | optional short name |

How a question is recognised: it starts like a question (هو/هي/هل/ليه/إمتى/إزاي/فين/كام…, what/how/when/can…) or is a sentence ending in "؟/?". Its keywords are matched first. If none match, the Mini's own language model (Gemma, already running locally) picks the FAQ that is *about* the same thing ("أنا جعان" → the food answer) or none. It only ever chooses one of your answers; it never writes one, so nothing improvised reaches a patient. If no FAQ fits, the agent says *"سؤال مهم، سجلته وحد من فريقنا هيرد عليك فيه. نرجع لسؤالنا."* (change it with **Arabic/English Off-Script Reply**) and asks again.

Every question a caller asked is kept: use `{{questions}}` in a Fixed Value, e.g. `Case.Description={{transcript}}` already contains them, or a dedicated field `Case.Comments__c={{questions}}`. Asking a question never counts as a failed answer. Answers that match a route (e.g. "is it new? yes, new") are still answers.

FAQ answers are voiced like every other line (and can be recorded in the studio). Measured on the Mini: matching takes 0.7–0.9 s when the keywords miss; nothing extra when they match.

## When a new or changed script is ready to take calls

Every line is voiced once, in the background, when you publish (about 20 seconds per line). A persona and language **opens for calls only when all of its lines are ready**, so a caller never gets a half-robotic or silent call. Until then the call page shows *"تحضير صوت مريم… 7/12 · Preparing Mariam's voice… 7/12"* on that button. The Mini finishes one persona and language completely before starting the next, and lines whose text did not change keep their audio, so a small edit is ready again in seconds.

## Questions, announcements, and routes

Questions run in **Order**. On each Question record:

| Field | Meaning |
| --- | --- |
| Order | 10, 20, 30… (gaps make inserting easy) |
| Answer Key | a short name for the answer, e.g. `full_name`, `menu`. Used in routes, Next, and `{{full_name}}` |
| Arabic Text / English Text | the line as it should be spoken. Write Arabic the way an Egyptian agent says it |
| Announcement | tick for a line that is spoken without waiting for an answer |
| Target Field | `Object.Field` the answer fills, e.g. `Contact.MobilePhone`. Blank = transcript only |
| Required | if nobody answers after the attempts, end the call politely |
| Attempts | how many times to ask (1–5) |
| Next | the Answer Key to go to next, or `goodbye`. Blank = the next question by Order. Also where a caller goes when no route matches |
| Routes | one per line: `keywords => next key [= stored value]` |

### Routes

A route sends the caller somewhere different based on what they said. For a menu question with Answer Key `menu`:

```
new, first time, جديد, جديدة, أول مرة => new_name = New
existing, follow, قديم, متابعة => case_number = Follow-up
```

- The first line with a keyword that appears in the answer wins. "لا دي حالة **جديدة** يا فندم" goes to `new_name`.
- Matching ignores case, punctuation, Arabic diacritics and spelling variants (أ/إ/ا, ة/ه, ى/ي), so "مُتابعه" still matches "متابعة". Put several ways of saying the same thing on one line.
- Callers mix languages, and keywords from **every** language of the script count on every line ("new" on the Arabic line routes too). Speech recognition often writes an English word said in an Egyptian sentence in Arabic letters ("new case" → "نيوكيس"), so add those spellings as keywords as well: `new, نيو, جديد`.
- `= New` stores **New** as the answer instead of the caller's words, which is what a picklist like `Case.Type` needs. Without it, the caller's words are stored.
- No match: the caller goes to **Next**. Point Next at a short announcement ("معلش، ما سمعتش كويس.") whose Next is the menu again, and the menu is asked again. A call ends politely after 40 answers, so a loop can never hold the line forever.
- A loop made only of announcements is refused at publish (it would talk forever).

## A complete example: Acme Pharma patient support

Two paths: new patients are onboarded (Contact + Case), existing patients are asked for their case number.

```
greeting (announcement)  "أهلاً، معاك {{company}}. أهلاً بيك في {{program}}."
hours    (announcement)  "الممرضات متاحين من ٩ الصبح لـ ٥ المسا."
menu     (question)      "إنت بتتصل علشان تسجيل جديد ولا متابعة لحالة قديمة؟"
   new…      → new_name      (stores Case.Type = New)
   existing… → case_number   (stores Case.Type = Follow-up)
   no match  → menu_again → menu
new_name     (question)  "ممكن تقولي اسمك بالكامل؟"       → Contact.LastName
mobile       (question)  "إيه رقم موبايلك؟"               → Contact.MobilePhone   → Next: goodbye
case_number  (question)  "إيه رقم الحالة؟"                → transcript only
goodbye  (closing)       "شكراً لاتصالك بـ{{company}}. ممرضة هتكلمك قريب."
```

### In Salesforce

**Voice Script** (Name *Acme PSP*, Script Id `acme-psp`):

| Field | Value |
| --- | --- |
| Languages | `ar-EG;en-US` |
| Variables | `company = Acme Pharma` / `company.ar = أكمي فارما` / `program = Acme Care` / `program.ar = برنامج أكمي كير` |
| Arabic Greeting | `أهلاً، معاك {{company}}. أهلاً بيك في {{program}}.` |
| English Greeting | `Hello, this is {{company}}. Welcome to {{program}}.` |
| Arabic Closing | `شكراً لاتصالك بـ{{company}}. ممرضة هتكلمك قريب.` |
| English Closing | `Thank you for calling {{company}}. A nurse will call you soon.` |
| Transcript Field | `Case.Description` |
| Fixed Values | `Case.Origin=Phone` / `Case.Status=New` / `Case.Subject={{program}} call` |
| Record Links | `Case.ContactId=Contact` |

**Questions:**

| Order | Answer Key | Announcement | Arabic / English | Target Field | Next | Routes |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | hours | ✓ | الممرضات متاحين من ٩ الصبح لـ ٥ المسا. / Our nurses are available 9 am to 5 pm. | | | |
| 20 | menu | | إنت بتتصل علشان تسجيل جديد ولا متابعة لحالة قديمة؟ / Are you calling to register, or about an existing case? | Case.Type | menu_again | `new, register, جديد, تسجيل => new_name = New` / `existing, follow, قديم, متابعة => case_number = Follow-up` |
| 30 | menu_again | ✓ | معلش، ما سمعتش كويس. / Sorry, I did not catch that. | | menu | |
| 40 | new_name | | ممكن تقولي اسمك بالكامل؟ / May I have your full name? | Contact.LastName | | |
| 50 | mobile | | إيه رقم موبايلك؟ / What is your mobile number? | Contact.MobilePhone | goodbye | |
| 60 | case_number | | إيه رقم الحالة؟ / What is your case number? | | | |

Then run **Publish Cloudiator voice script** on the record. The Mini voices every line in the background; calls use it as soon as it is ready.

### The same script as JSON

For integrations that publish without Salesforce: `POST https://api.cloudiator.org/v1/voice/scripts` with a key that has the `voice` capability.

```json
{
  "id": "acme-psp",
  "display_name": "Acme PSP",
  "languages": ["ar-EG", "en-US"],
  "variables": {
    "company": {"ar-EG": "أكمي فارما", "en-US": "Acme Pharma"},
    "program": {"ar-EG": "برنامج أكمي كير", "en-US": "Acme Care"}
  },
  "steps": [
    {"key": "greeting", "next": "hours",
     "say": {"ar-EG": "أهلاً، معاك {{company}}. أهلاً بيك في {{program}}.",
             "en-US": "Hello, this is {{company}}. Welcome to {{program}}."}},
    {"key": "hours", "next": "menu",
     "say": {"ar-EG": "الممرضات متاحين من ٩ الصبح لـ ٥ المسا.", "en-US": "Our nurses are available 9 am to 5 pm."}},
    {"key": "menu", "gather": true, "next": "menu_again",
     "say": {"ar-EG": "إنت بتتصل علشان تسجيل جديد ولا متابعة لحالة قديمة؟",
             "en-US": "Are you calling to register, or about an existing case?"},
     "routes": [
       {"when": ["new", "register", "جديد", "تسجيل"], "next": "new_name", "value": "New"},
       {"when": ["existing", "follow", "قديم", "متابعة"], "next": "case_number", "value": "Follow-up"}
     ]},
    {"key": "menu_again", "next": "menu",
     "say": {"ar-EG": "معلش، ما سمعتش كويس.", "en-US": "Sorry, I did not catch that."}},
    {"key": "new_name", "gather": true, "next": "mobile",
     "say": {"ar-EG": "ممكن تقولي اسمك بالكامل؟", "en-US": "May I have your full name?"}},
    {"key": "mobile", "gather": true, "next": "goodbye",
     "say": {"ar-EG": "إيه رقم موبايلك؟", "en-US": "What is your mobile number?"}},
    {"key": "case_number", "gather": true, "next": "goodbye",
     "say": {"ar-EG": "إيه رقم الحالة؟", "en-US": "What is your case number?"}},
    {"key": "goodbye", "next": null,
     "say": {"ar-EG": "شكراً لاتصالك بـ{{company}}. ممرضة هتكلمك قريب.",
             "en-US": "Thank you for calling {{company}}. A nurse will call you soon."}}
  ],
  "commit": {"records": [
    {"sobject": "Contact", "fields": {"LastName": "{{new_name}}", "MobilePhone": "{{mobile}}"}},
    {"sobject": "Case", "after": ["Contact"], "fields": {
      "ContactId": "{{Contact.Id}}", "Type": "{{menu}}", "Origin": "Phone", "Status": "New",
      "Subject": "{{program}} call", "Description": "{{transcript}}"}}
  ]}
}
```

## Recipes

**A new client, same flow.** Clone the Voice Script and its Questions, change Variables and Script Id, publish, mint a call link.

**Different questions per client.** Each client gets their own script; edit its Questions. Order controls the sequence; Next and Routes override it.

**An announcement in the middle.** Add a Question with *Announcement* ticked at the right Order.

**A different greeting for a campaign.** Change the Greeting (or a variable such as `campaign = Ramadan offer`) and publish. Only the changed lines are re-voiced.

**A person's voice instead of the generated one.** Mint a studio link (`POST /v1/voice/scripts/{id}/studio-link`), open it, and record each line. Recordings win over generated audio on the next call. See [voice.md](voice.md#recording-studio-peoples-voices-nothing-leaves-the-mini).

**Put the call button on a website.** Mint a call link (`POST /v1/voice/scripts/{id}/web-link`) and link to it, e.g. `<a href="https://api.cloudiator.org/v1/voice/web/cl_…">Call us</a>`. Revoke with `POST /v1/voice/scripts/{id}/web-link/revoke` (also revokes studio links).

**Where the answers go.** Finished calls are `ready_to_commit`. Run **Commit Cloudiator voice sessions** in Salesforce (or schedule it) to create the records and ack them.

## Limits

- Up to 50 steps per script, 10 routes per question, 30 variables, 6 personas, 4 languages (Arabic and English have text fields in Salesforce).
- Every persona multiplies the lines to voice: 3 personas × 2 languages × 10 lines = 60 clips, about 20 minutes of background rendering on the Mini after a publish. Calls work meanwhile with the basic voice.
- One call at a time on the Mini; other callers wait in line and hear the hold message.
- A call ends after 40 answers.
