# Note Lock Webhook

## What it does

Note Lock Webhook watches note state changes in Canvas and pushes a small payload to an endpoint of your choice the moment a note is **signed**.

Canvas emits a note state change event for every transition a note goes through — created, locked, unlocked, deleted, signed. This plugin listens to all of them but only acts on `SGN` (signed). When that transition happens, it POSTs:

```json
{
  "state": "SGN",
  "note_id": "<note id>",
  "patient_id": "<patient id>"
}
```

That's deliberately minimal. The note id and patient id are the two keys you need to call the Canvas FHIR API for whatever else you want — the full note body, the encounter, the patient's chart — so the webhook stays fast and carries no PHI beyond identifiers.

## Problem it solves

A signed note is the moment clinical documentation becomes final, and it's the natural trigger for everything downstream: billing and coding review, care-coordination handoffs, quality reporting, syncing the note into a data warehouse, kicking off a patient follow-up.

Without a push signal, external systems have to poll the FHIR API on a timer and diff results to notice a note was signed. That's wasteful when nothing changed, and it adds latency exactly when you don't want it. This plugin inverts it: Canvas tells your system the instant a note is signed, and your system decides what to fetch.

## Who it's for

| Role | Primary use |
|---|---|
| Engineering / integrations team | Trigger downstream jobs off signed documentation instead of polling FHIR |
| Revenue cycle / billing ops | Start coding and claim review as soon as a note is final |
| Data / analytics team | Stream signed notes into a warehouse or pipeline in near real time |
| Care coordination | Fire handoffs, referrals, or patient outreach when documentation completes |

**Specialty:** not specialty-specific. Any Canvas instance where notes get signed will emit these events.

## How to install

1. Install the plugin into your Canvas instance:

   ```bash
   canvas install note_lock_webhook
   ```

2. Set the plugin secrets in the Canvas admin UI, under the plugin's settings (see [Configuration options](#configuration-options)). `WEBHOOK_URL` is required — the plugin will not be able to send anything until it is set.

3. Sign a note in Canvas and confirm your endpoint receives the payload. Plugin logs are visible with:

   ```bash
   canvas logs
   ```

No SDK feature flags or additional Canvas settings need to be enabled — the note state change event this plugin subscribes to is available by default.

### Requirements

- Canvas SDK `0.1.4` or later
- An HTTPS endpoint that accepts `POST` with a JSON body

## Configuration options

Both options are Canvas **plugin secrets**, set per-instance in the admin UI. Nothing needs to be changed in the source.

| Secret | Required | Description |
|---|---|---|
| `WEBHOOK_URL` | Yes | The endpoint the payload is POSTed to. Receives `Content-Type: application/json`. |
| `AUTH_TOKEN` | No | If set, sent as `Authorization: Bearer <token>`. Leave unset if your endpoint doesn't need authentication. |

To change *which* note state triggers the webhook, edit the `SIGNED_STATE` constant in `note_lock_webhook/protocols/note_lock_webhook.py` — for example, set it to `"LKD"` to fire on lock instead of sign.

## Architecture

```
note_lock_webhook/
├── CANVAS_MANIFEST.json                  # plugin manifest; declares the protocol and secrets
└── protocols/
    └── note_lock_webhook.py              # NOTE_STATE_CHANGE_EVENT_UPDATED handler
```

## Behavior notes

- Non-signed state changes return immediately without making a request, so the plugin is inert for the majority of note events.
- A non-2xx response from the webhook is logged as an error; the plugin does not retry. If delivery guarantees matter, have your endpoint enqueue the payload and acknowledge quickly.
- The protocol returns no effects — it does not modify anything in Canvas.

## Running tests

```bash
uv run pytest tests/
```
