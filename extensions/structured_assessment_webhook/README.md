# Structured Assessment Webhook

## What it does

Structured Assessment Webhook listens for structured assessment commits in Canvas and POSTs to an external endpoint when a specific assessment carries a specific answer.

As shipped, it watches for a committed *Health Coaching ABT* assessment where a particular question carries a particular answer, and sends:

```json
{
  "contents": {
    "note_id": "...",
    "patient_id": "..."
  }
}
```

That's deliberately minimal. The note id and patient id are the two keys needed to call the Canvas FHIR API for anything else — the full assessment, the encounter, the patient chart — so the webhook stays fast and carries no PHI beyond identifiers. In the deployment this came from, the receiving system uses them to count the encounter toward CCM minutes.

### The shipped values are an example

**The assessment title, question ID, and answer ID are specific to the Canvas instance this was written for.** Your instance will use different ones — `question-3973` does not exist anywhere else. They are constants at the top of the protocol file, and changing them repurposes the plugin to fire on **any specific answer to any structured assessment** in the Canvas UI. See [Configuration options](#configuration-options).

Anything that doesn't match both gates is ignored, so the plugin stays inert for the rest of your assessments.

## Problem it solves

Structured assessments capture the answers that determine whether an encounter qualifies for something — a care-management program, a billable service, a follow-up pathway. But that answer lands inside a note, and whatever system acts on it has to go looking.

Care management is the clearest case: whether a visit counts toward CCM minutes often hinges on a single answer, and the tracking system needs to know at the moment it's recorded, not at month-end when someone runs a report. Without a push signal, external systems poll the FHIR API on a timer and reconstruct the answer after the fact — wasteful when nothing changed, and slow exactly when it matters.

This plugin inverts that: the instant a qualifying assessment is committed, the encounter is already at your endpoint.

## Who it's for

| Role | Primary use |
|---|---|
| Care management (CCM/RPM) | Count qualifying encounters toward program minutes in real time |
| Engineering / integrations team | Trigger downstream work off a specific assessment answer |
| Revenue cycle / billing ops | Flag billable encounters the moment the determining answer is recorded |
| Quality / population health | Route screening or eligibility answers to a tracking system as captured |
| Data / analytics team | Stream qualifying assessments into a warehouse as they happen |

**Specialty:** not specialty-specific. Any Canvas instance using structured assessments can use this; the shipped example is a health-coaching workflow.

## How to install

1. Install the plugin into your Canvas instance:

   ```bash
   canvas install structured_assessment_webhook
   ```

2. Set the plugin secrets in the Canvas admin UI, under the plugin's settings (see [Configuration options](#configuration-options)). `WEBHOOK_URL` is required — if it is unset, the plugin logs an error and skips the request.

3. Edit the constants at the top of `structured_assessment_webhook/protocols/structured_assessment_webhook.py` to match your own assessment — the shipped values will not match your instance.

4. Commit a matching assessment in Canvas and confirm your endpoint receives the payload. Plugin logs are visible with:

   ```bash
   canvas logs
   ```

No SDK feature flags or additional Canvas settings need to be enabled — the structured assessment commit event this plugin subscribes to is available by default.

### Requirements

- Canvas SDK `0.1.4` or later
- An HTTPS endpoint that accepts `POST` with a JSON body

## Configuration options

### Plugin secrets

Set per-instance in the Canvas admin UI. Nothing needs to be changed in the source for these.

| Secret | Required | Description |
|---|---|---|
| `WEBHOOK_URL` | Yes | The endpoint the payload is POSTed to. Receives `Content-Type: application/json`. If unset, the plugin logs an error and skips. |
| `AUTH_TOKEN` | No | If set, sent as `Authorization: Bearer <token>`. Leave unset if your endpoint doesn't need authentication. |

### Source constants

These are **instance-specific and must be edited** — they are at the top of `structured_assessment_webhook/protocols/structured_assessment_webhook.py`.

| Constant | What it controls |
|---|---|
| `ASSESSMENT_TITLE` | Exact assessment title that triggers the webhook. Matched exactly, including case. |
| `QUESTION_KEY` | The gating question, as `question-<id>`. **The shipped `question-3973` is from another instance — replace it with your own question ID.** |
| `ANSWER_ID` | The answer ID that must match for the webhook to fire. Replace alongside the question ID. Compared by identity, so an integer ID will not match the string `"7550"`. |

You can find question and answer IDs in the assessment's definition in the Canvas admin UI.

To send more than the note and patient id, add the fields you want to the `payload` dict in `compute()` — the rest of the committed answers are available on `fields`.

## Architecture

```
structured_assessment_webhook/
├── CANVAS_MANIFEST.json                          # plugin manifest; declares the protocol and secrets
└── protocols/
    └── structured_assessment_webhook.py          # STRUCTURED_ASSESSMENT_COMMAND__POST_COMMIT handler
```

## Behavior notes

- Assessments failing either gate return immediately without making a request, so the plugin is inert for the majority of commits.
- A non-2xx response is logged as an error; the plugin does not retry. If delivery guarantees matter, have your endpoint enqueue the payload and acknowledge quickly.
- Missing note or patient data yields `null` in the payload rather than raising.
- The protocol returns no effects — it does not modify anything in Canvas.

## Running tests

```bash
uv run pytest tests/
```
