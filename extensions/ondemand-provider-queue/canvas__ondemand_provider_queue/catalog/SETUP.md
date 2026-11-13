## Before you start

- The note type new visits should use (an on-demand or virtual visit type) and the practice location to fall back to.
- Something that will send visit requests: a form, a website, or a partner system able to make an authenticated web request.
- Two or three test patients if you want to try the demo tools.

## Settings

- `QUEUE_ENABLED` (default `false`): turns the queue on. While off, the screen and the request address answer "turned off" and nothing changes.
- `QUEUE_API_KEY` (required, sensitive): a long random key the sending system uses as a Bearer token. Requests are refused while it is blank.
- `DEFAULT_NOTE_TYPE_ID` (required): the note type used when a visit starts.
- `DEFAULT_PRACTICE_LOCATION_ID` (required): the location used when a request names none.
- `QUEUE_STAFF_IDS` (optional): comma-separated staff ids allowed to use the queue. Blank means every signed-in staff member.
- `DEMO_MODE_ENABLED` (default `false`) and `DEMO_PATIENT_IDS`: `true` shows buttons that add the listed test patients and clear the queue. Test instances only.
- `QUEUE_STORAGE` (default `canvas`): leave as `canvas`. `s3` keeps the queue in the practice's own S3 bucket instead and needs `AWS_ACCESS_KEY`, `AWS_SECRET_KEY` (both sensitive), `S3_BUCKET`, `S3_REGION` and optionally `S3_OBJECT_KEY`. With S3, two changes at the same instant can overwrite each other.

## Steps

1. Install the plugin. Set `QUEUE_API_KEY`, `DEFAULT_NOTE_TYPE_ID` and `DEFAULT_PRACTICE_LOCATION_ID`, then set `QUEUE_ENABLED` to `true`.
2. Open **Provider Queue** from the app drawer as a provider.
3. On a test instance, set `DEMO_MODE_ENABLED` to `true` and `DEMO_PATIENT_IDS` to your test patients, then choose **+ Add Demo Patient**. Or send a request for a test patient with the example in the README.
4. Assign the request, choose **Start Visit**, and check a note opens on the test patient.
5. Lock the note and check the entry moves to **Completed**.
6. Turn `DEMO_MODE_ENABLED` off before real use.
