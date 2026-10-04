# Questionnaire Webhook

## What it does

Questionnaire Webhook listens for questionnaire commits in Canvas, picks out specific answers, and POSTs them to an external endpoint.

The plugin ships with **two working example branches**, both drawn from a real deployment:

**Branch A — CCM-eligible encounters.** When an *RDP Encounter Type* questionnaire is committed and a particular question carries a particular answer, the note id and patient id are sent to a CCM endpoint:

```json
{ "contents": { "note_id": "...", "patient_id": "..." } }
```

**Branch B — prior-authorization medication fields.** When a questionnaire whose title starts with `PA` is committed, the medication fields are extracted and sent to a PA endpoint:

```json
{
  "contents": {
    "note_id": "...",
    "patient_id": "...",
    "questionnaire_id": "...",
    "questionnaire": {
      "drug_name": "...", "strength": "...", "dose_form": "...",
      "quantity": "...", "days_supply": "...", "directions": "...",
      "dispense_unit": "...", "route_of_administration": "...",
      "prescription_date": "..."
    }
  }
}
```

### These are examples, not a fixed feature set

**The two branches are templates.** The questionnaire titles, the gating question and answer, and the medication field labels are all specific to the Canvas instance this plugin was written for — your instance will use different ones. The plugin is designed to be repurposed: the same pattern captures **any specific answers from any questionnaire** in the Canvas UI and forwards them wherever you need. See [Configuration options](#configuration-options) for exactly what to change.

Anything that matches neither branch is ignored, so the plugin stays inert for the rest of your questionnaires.

## Problem it solves

Questionnaires are where a lot of structured clinical and administrative data actually gets captured — screening scores, encounter types, prior-auth details, intake answers. But that data lands inside a note, and any system that needs to act on it has to go looking.

Prior authorization is the clearest case: the drug, strength, quantity, and directions are all typed into a questionnaire, then someone re-keys them into a payer portal. Same for billing-relevant encounter flags, which sit in a note until a report picks them up later.

Without a push signal, external systems poll the FHIR API and reconstruct answers after the fact. This plugin inverts that: the moment a questionnaire is committed, the answers you care about are already at your endpoint, keyed by note and patient id so you can pull the rest from the Canvas FHIR API if you need it.

## Who it's for

| Role | Primary use |
|---|---|
| Engineering / integrations team | Forward structured questionnaire answers into any external system |
| Prior-authorization staff | Get medication details to a PA workflow without re-keying them |
| Revenue cycle / billing ops | Flag billable encounter types the moment they're recorded |
| Care management (CCM/RPM) | Route program-eligibility answers to a tracking system in real time |
| Data / analytics team | Stream questionnaire responses into a warehouse as they're captured |

**Specialty:** not specialty-specific. Any Canvas instance using questionnaires can use this; the shipped branches are ambulatory examples.

## How to install

1. Install the plugin into your Canvas instance:

   ```bash
   canvas install questionnaire_webhook
   ```

2. Set the plugin secrets in the Canvas admin UI, under the plugin's settings (see [Configuration options](#configuration-options)). Each branch needs its own URL; a branch whose URL is unset logs an error and skips its POST, so you can run just one branch by setting only that secret.

3. Edit the constants at the top of `questionnaire_webhook/protocols/questionnaire_webhook.py` to match your own questionnaires — the shipped values will not match your instance.

4. Commit a matching questionnaire in Canvas and confirm your endpoint receives the payload. Plugin logs are visible with:

   ```bash
   canvas logs
   ```

No SDK feature flags or additional Canvas settings need to be enabled — the questionnaire commit event this plugin subscribes to is available by default.

### Requirements

- Canvas SDK `0.1.4` or later
- An HTTPS endpoint that accepts `POST` with a JSON body

## Configuration options

### Plugin secrets

Set per-instance in the Canvas admin UI. Nothing needs to be changed in the source for these.

| Secret | Required | Description |
|---|---|---|
| `CCM_WEBHOOK_URL` | For Branch A | Endpoint for CCM-eligible encounter payloads. If unset, Branch A logs an error and skips. |
| `PA_WEBHOOK_URL` | For Branch B | Endpoint for prior-authorization payloads. If unset, Branch B logs an error and skips. |
| `AUTH_TOKEN` | No | If set, sent as `Authorization: Bearer <token>` on both branches. |

### Source constants

These are **instance-specific and must be edited** — they are at the top of `questionnaire_webhook/protocols/questionnaire_webhook.py`.

| Constant | What it controls |
|---|---|
| `CCM_QUESTIONNAIRE_TITLE` | Exact questionnaire title that triggers Branch A. |
| `CCM_QUESTION_KEY` | The gating question, as `question-<id>`. **The shipped `question-3331` is from another instance — replace it with your own question ID.** |
| `CCM_ANSWER_ID` | The answer ID that must match for Branch A to fire. Replace alongside the question ID. |
| `PA_TITLE_PREFIX` | Title prefix that triggers Branch B. Matches on prefix, so every `PA…` questionnaire is picked up. |
| `LABEL_TO_PAYLOAD_KEY` | Maps question labels on the questionnaire to keys in the outgoing payload. Labels must match exactly; unlisted questions are ignored. Add, remove, or rename freely. |

You can find question and answer IDs in the questionnaire's definition in the Canvas admin UI.

### Repurposing it for a different questionnaire

To capture different answers entirely, the shape stays the same: match on the questionnaire title, pull the answers you want out of `fields`, and call `self._post()` with a secret name and payload. Branch A shows the single-answer gate; Branch B shows label-driven extraction of many answers at once.

## Architecture

```
questionnaire_webhook/
├── CANVAS_MANIFEST.json                    # plugin manifest; declares the protocol and secrets
└── protocols/
    └── questionnaire_webhook.py            # QUESTIONNAIRE_COMMAND__POST_COMMIT handler
```

## Behavior notes

- Questionnaires matching neither branch return immediately without making a request.
- A non-2xx response is logged as an error; the plugin does not retry. If delivery guarantees matter, have your endpoint enqueue the payload and acknowledge quickly.
- Missing note, patient, or question data yields `null` in the payload rather than raising.
- The protocol returns no effects — it does not modify anything in Canvas.

## Running tests

```bash
uv run pytest tests/
```
