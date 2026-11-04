# Installing On-Demand Provider Queue (canvas__ondemand_provider_queue)

The plugin adds one app-drawer screen, one API route for an outside sender, staff-only routes for the screen, a staff-only websocket and a handler that completes entries when a note is locked. Queue entries are stored in the plugin's custom data namespace `canvas__ondemand_provider_queue`, one row per entry.

## Settings to collect

- `QUEUE_ENABLED`: `false` until step 3, then `true`.
- `QUEUE_API_KEY` (sensitive): generate a random key of 32 or more characters. Give it to the sending system only.
- `DEFAULT_NOTE_TYPE_ID`: id of an active note type for on-demand visits.
- `DEFAULT_PRACTICE_LOCATION_ID`: id of an active practice location.
- `QUEUE_STAFF_IDS`: blank, or the staff ids allowed to use the screen.
- `DEMO_MODE_ENABLED` / `DEMO_PATIENT_IDS`: `false` / blank outside test instances. Never list real patients.
- `QUEUE_STORAGE`: `canvas`. Use `s3` only if the practice asks to keep its existing S3 queue; then also collect `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_OBJECT_KEY`.

## Steps

1. Install with `QUEUE_ENABLED` set to `false` and the settings above.
2. Check the request address refuses work while off: `POST /plugin-io/api/canvas__ondemand_provider_queue/intake/queue-request` returns 503.
3. Set `QUEUE_ENABLED` to `true`.
4. Check: without the Bearer key the same request returns 401. With it, and a test patient id plus `reason_for_visit`, it returns 201. Sending the same `external_id` again returns 200 with the same `entry_id`.
5. Open **Provider Queue**, assign the entry, choose **Start Visit**. A note appears on the test patient.
6. Lock the note. The entry moves to **Completed**.
7. Never test on a real patient's chart.
