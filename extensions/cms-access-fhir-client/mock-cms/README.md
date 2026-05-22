# Mock CMS ACCESS server

Tiny FastAPI server that mimics enough of the CMS ACCESS FHIR API for end-to-end testing of `cms-access-fhir-client` from a deployed Canvas instance (e.g. `allison-training`).

## What it serves

| Method | Path | Returns |
|---|---|---|
| POST | `/oauth/token` | Fake bearer token (`{access_token, expires_in: 300}`) |
| POST | `/access/Patient/$check-eligibility?entityId=<id>` | 200 + FHIR Parameters with `status: eligible` |
| POST | `/access/Patient/$align?entityId=<id>` | 202 + `Content-Location: /submission/<id>` |
| POST | `/access/Patient/$unalign?entityId=<id>` | 202 + `Content-Location: /submission/<id>` |
| GET | `/submission/{id}` | 202 + empty body + `X-Progress` header on first `POLLS_BEFORE_COMPLETE` polls, then 200 + Parameters body on completion |
| GET | `/submission/{id}?force_error=true` | 200 + OperationOutcome body (tests error-parsing path) |
| GET | `/_state` | Debug — inspect in-memory submissions |

## Run

```bash
cd mock-cms
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## Expose to allison-training

Pick one — Canvas needs a public URL:

```bash
# Cloudflare quick tunnel (no account needed)
cloudflared tunnel --url http://localhost:8000

# or ngrok
ngrok http 8000
```

Copy the public URL it prints — e.g. `https://abc-123.trycloudflare.com`.

## Configure the plugin

In the Canvas admin (`/admin/plugin_io/plugin/<id>/change/`) set:

| Variable | Value |
|---|---|
| `ACCESS_BASE_URL` | `https://<your-tunnel>` |
| `ACCESS_OAUTH_TOKEN_URL` | `https://<your-tunnel>/oauth/token` |
| `ACCESS_OAUTH_CLIENT_ID` | any non-empty string |
| `ACCESS_OAUTH_CLIENT_SECRET` | any non-empty string |
| `ACCESS_OAUTH_SCOPE` | leave blank (defaults to `cdx/*.read cdx/fhir-resource.write`) |
| `ACCESS_PARTICIPANT_ID` | `ACCES10098` (five-letter `ACCES` prefix + 5 digits — matches real CMS format) |
| `ACCESS_WEBHOOK_SECRET` | pick any value — you'll pass it to `send_webhook.py` |
| `ACCESS_SHOW_BANNER` | `true` |
| `ACCESS_SHOW_CHART_SUMMARY` | `true` |

### Real CMS testing (Cycle 2 opens May 26)

| Variable | Value |
|---|---|
| `ACCESS_BASE_URL` | `https://impl-cdxapi.cmmi.cms.gov/cdx/services/fhir` |
| `ACCESS_OAUTH_TOKEN_URL` | `https://impl.idp.idm.cms.gov/oauth2/ausqf73jnuHioLLg3297/v1/token` |
| `ACCESS_PARTICIPANT_ID` | your assigned entity ID (format: `ACCES` + 5 digits, e.g. `ACCES10098`) |

> Note: the entity ID prefix is **ACCES** (5 letters), not **ACCESS** (6 letters).

## Authentication

The mock enforces HTTP Basic auth on the token endpoint, matching real CMS behaviour.
The `Authorization: Basic <base64(client_id:client_secret)>` header must be present.
Any credential values are accepted; only the encoding format is validated.

## Submission polling state machine

```
POST $align/$unalign → 202 + Content-Location
GET /submission/{id} → 202 + empty body + X-Progress header  (polls 1..POLLS_BEFORE_COMPLETE)
GET /submission/{id} → 200 + Parameters body                 (poll POLLS_BEFORE_COMPLETE+1)
GET /submission/{id}?force_error=true → 200 + OperationOutcome body  (any poll)
```

`POLLS_BEFORE_COMPLETE = 1` (default) means the second GET returns completed.
Adjust in `app.py` if you want longer in-progress windows.

## End-to-end flow to exercise

1. Open any patient chart on `allison-training`.
2. Click **Check ACCESS Eligibility** → mock returns `eligible` synchronously → banner / chart summary should update.
3. Click **Enroll in ACCESS** → pick a track + justification → submit. Plugin stores `submission_status_url` from `Content-Location`.
4. Wait ~1 min — `SubmissionStatusPoller` runs, polls the mock. First poll returns `202 in-progress`; second poll returns `200 completed` with an `alignmentId` and `careStartDate`. Alignment row should update.
5. Test error path: manually set `ACCESS_BASE_URL` submission URL to include `?force_error=true` (or query the `/_state` endpoint to find the sub_id and craft the URL).
6. Drive an inbound subscription event:

   ```bash
   uv run python send_webhook.py alignment-renewal-due --secret <your-webhook-secret>
   ```

   Should return 200 and create an `ACCESSWebhookEvent` row.

## Caveats

- In-memory only — restart the server and all submissions are gone.
- The mock returns `expires_in: 300` (5 minutes) on the token endpoint, matching real CMS.
