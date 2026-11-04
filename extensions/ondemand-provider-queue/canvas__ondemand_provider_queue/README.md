# On-Demand Provider Queue

A live queue for on-demand visits. An outside system adds patients through an API; staff work the queue from the **Provider Queue** app.

Original 0.7.2 author unknown; adapted from the version deployed on customer sandboxes. This catalog version moves storage into Canvas custom data, closes the open routes, and makes every setting configurable.

## How it works

```
awaiting_assignment -> waiting_for_provider -> in_progress <-> paused -> complete
```

- `POST /intake/queue-request` adds an entry (`awaiting_assignment`).
- Assigning a provider moves it to `waiting_for_provider`. Only one assignment can win; a second one gets "Entry already claimed".
- **Start Visit** creates the note (note type `DEFAULT_NOTE_TYPE_ID`, provider = the assigned provider, location = the request's or `DEFAULT_PRACTICE_LOCATION_ID`) and records its id on the entry. Clicking again returns the same note; it never creates a second one.
- Locking that note marks the entry `complete`.

Each entry is a `QueueEntryRecord` row in the `canvas__ondemand_provider_queue` namespace. Every change is one conditional update, so simultaneous clicks can't overwrite each other.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUEUE_ENABLED` | `false` | Master switch. Off: every route answers 503 and the note handler does nothing. |
| `QUEUE_API_KEY` (sensitive) | blank | Bearer key for the intake route. Blank refuses every request. |
| `QUEUE_STAFF_IDS` | blank | Comma-separated staff ids allowed on the screen. Blank: any signed-in staff. |
| `DEFAULT_NOTE_TYPE_ID` | blank | Note type for Start Visit (required to start). |
| `DEFAULT_PRACTICE_LOCATION_ID` | blank | Location when the request has none (required to start). |
| `DEMO_MODE_ENABLED` | `false` | Shows Add Demo Patient / Clear Queue. |
| `DEMO_PATIENT_IDS` | blank | The only patients the demo button may add. |
| `QUEUE_STORAGE` | `canvas` | `s3` stores the whole queue as one JSON file in your bucket (last write wins). |
| `AWS_ACCESS_KEY`, `AWS_SECRET_KEY` (sensitive), `S3_BUCKET`, `S3_REGION`, `S3_OBJECT_KEY` | blank / `ondemand-provider-queue/queue.json` | Only used with `QUEUE_STORAGE=s3`. |

## Sending a request

```bash
curl -X POST "https://<instance>.canvasmedical.com/plugin-io/api/canvas__ondemand_provider_queue/intake/queue-request" \
  -H "Authorization: Bearer $QUEUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "<test patient id>", "reason_for_visit": "Follow-up visit", "priority": "routine", "external_id": "req-123"}'
```

- `patient_id` and `reason_for_visit` are required; the patient must exist.
- `priority`: `routine` (default), `urgent` or `emergent`.
- `external_id` (optional): your request id. Sending it again returns the existing entry (200) instead of adding a second one (201).
- `practice_location_id` (optional).

## Staff routes

All under `/plugin-io/api/canvas__ondemand_provider_queue/routes`, signed-in staff only: `GET /ui/queue`, `GET /config`, `GET /staff`, `GET /queue[?view=completed]`, `POST /claim-entry`, `POST /update-assignment`, `POST /start-visit`, `POST /pause-visit`, `POST /resume-visit`, and with demo mode `POST /demo-add-patient`, `POST /demo-clear-queue`.

The websocket `/plugin-io/ws/canvas__ondemand_provider_queue/queue/` carries "something changed" messages with ids only; the screen re-fetches the queue on every message and reconnect.
