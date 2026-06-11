# EHI Export

A staff-facing Canvas application — shown in the **provider (hamburger) menu** —
for exporting patients' complete **Electronic Health Information (EHI)** across
the patient population. Pick patients (one, several, or *everyone matching a
filter*), and the plugin exports each patient's full record as a single JSON
file, prepared in the background and downloadable from S3.

It's built so that **whole-instance exports never overload Canvas**: work is
queued and drained by a throttled background task (see
[Performance, batching & configurability](#performance-batching--configurability)).

---

## What it does

- **Browse & find patients** — a paginated, sortable table (last name, first
  name, DOB, active status, patient ID). Search by **name or patient ID**.
- **Filter** by active/inactive and by **export status** (completed, failed,
  in progress, queued, or never exported) — filters apply on **Apply**.
- **Export** in three ways:
  - **Export** button on any row — a single patient.
  - **Export selected** — the patients you've checked.
  - **Export all matching** — everyone in the current filter, queued server-side
    (no row-by-row selection, no client-side cap).
- **Fire-and-forget** — every export is *queued* instantly and runs in the
  background. You can close the page and come back.
- **Track runs** — each "export" action becomes a **run**. The main page shows
  the latest 5; **Show all runs** opens a paginated, searchable, sortable list.
  Runs are attributed to the **staff member who started them**.
- **Download** — completed patients are stored in S3 and downloaded via a
  short-lived presigned link (per patient, or grab a whole run's folder with
  `aws s3 sync`). Nothing is assembled in browser memory.
- **Recover from failures** — failed patients show their error message; a run
  with failures offers **Re-run failed**, which queues just those patients as a
  new run.

### The export format

Each patient is one JSON document — a FHIR `Bundle` whose entries are **grouped
by resource type**:

```json
{
  "resourceType": "Bundle",
  "type": "collection",
  "id": "ehi-export-<patient-id>",
  "total": 37,
  "entry": {
    "Appointment": { "total": 5, "entry": [ /* FHIR resources */ ] },
    "Patient":     { "total": 1, "entry": [ /* FHIR resources */ ] }
  }
}
```

---

## How it works

The export is the Canvas FHIR **Bulk Data** (`$export`) operation, which is
asynchronous per patient. The plugin drives it as a server-side pipeline:

1. **Enqueue** — an export action records one `queued` job per patient (with the
   run/batch id and the staff member). No `$export` is called here, so queuing
   thousands of patients is instant.
2. **Start (throttled)** — a background `CronTask` starts `$export` for queued
   jobs, but only up to a **global in-flight cap** (see below). `$export` is
   `Prefer: respond-async`, so each start returns immediately; Canvas generates
   the ~31 FHIR resource files per patient on its worker tier.
3. **Advance** — the cron polls each in-progress job's `bulkstatus` until it
   reports complete.
4. **Prepare** — for completed jobs, the cron downloads the NDJSON files, merges
   them into the grouped Bundle, and uploads one JSON object to S3
   (`<prefix>/<run-id>/<Last_First>_<patient-id>.json`).
5. **Download** — the UI requests a presigned S3 URL per patient. If a file
   isn't prepared yet, it's prepared on demand for that one patient.

The UI auto-refreshes every ~12s so `queued → in-progress → complete` transitions
appear without a manual reload.

### Authentication

The plugin extends the Canvas SDK FHIR client
(`canvas_sdk.clients.canvas_fhir.CanvasFhir`), which performs the OAuth2
client-credentials grant and caches the token. The base client only does CRUD,
so a small subclass (`EHIExportClient`) adds the `$export` / `bulkstatus` /
NDJSON operations. The FHIR and EMR hosts are derived automatically from
`CUSTOMER_IDENTIFIER` — you only configure the OAuth client id/secret.

---

## Performance, batching & configurability

Exporting a large population could otherwise overwhelm Canvas (thousands of
concurrent bulk-export jobs). This plugin prevents that with a **server-side
queue and a global concurrency ceiling** — not by limiting how many patients you
can pick.

**Why batching, not browser concurrency.** Because `$export` is
`respond-async`, *starting* an export is cheap (a 202 returns instantly); the
real load is Canvas **generating files for many patients at once**. So the
throttle is the number of jobs **concurrently in-progress**, enforced in the
cron:

```
slots_this_tick = min(EHI_START_PER_TICK, EHI_MAX_IN_FLIGHT − jobs_currently_in_progress)
```

No matter how many patients are queued, at most `EHI_MAX_IN_FLIGHT` exports are
ever generating on Canvas simultaneously. The queue drains itself over
successive cron ticks.

**Bounded work per tick.** Each cron run also caps the heaviest step — preparing
files (≈31 downloads + an S3 upload per patient) — to a small number, so no
single tick runs long.

**Tuning.** All of the knobs are plugin variables (no redeploy to change):

| Variable | Default | What it controls |
|----------|---------|------------------|
| `EHI_POLL_SCHEDULE` | `*/5 * * * *` | Cron cadence (5-field cron expression). Tighten for faster throughput. |
| `EHI_MAX_IN_FLIGHT` | `10` | Max export jobs generating on Canvas at once (the global ceiling). |
| `EHI_START_PER_TICK` | `10` | Max new jobs started per cron tick. |

Guidance: raise `EHI_MAX_IN_FLIGHT` / `EHI_START_PER_TICK` and/or use a tighter
schedule on a beefy instance to export faster; lower them on a constrained one.
Throughput ≈ how fast jobs complete × the in-flight ceiling.

**Memory & request safety.** Per-patient JSON is built one patient at a time
(server-side, in the cron or an on-demand download) — never a whole-instance
payload in one request, and never a ZIP assembled in browser memory. Downloads
stream straight from S3 via presigned URLs.

---

## Configuration

Set these on the plugin's configuration page.

### Required — FHIR API

| Variable | Description |
|----------|-------------|
| `CANVAS_FHIR_CLIENT_ID` | OAuth application client id (client-credentials grant). |
| `CANVAS_FHIR_CLIENT_SECRET` | OAuth application client secret. |

Create the OAuth application at
`https://<instance>.canvasmedical.com/auth/applications/` with **Client Type:
Confidential** and **Authorization Grant Type: Client credentials**, and grant
it permission to run the patient `$export` operation.

### Required — S3 storage

| Variable | Description |
|----------|-------------|
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | IAM credentials with `s3:PutObject` and `s3:GetObject` on the bucket/prefix. |
| `S3_REGION` | Bucket region, e.g. `us-east-1`. |
| `S3_BUCKET` | Target bucket. |
| `S3_PREFIX` | Optional key prefix (default `ehi-exports`). |

Without S3, exports still run and are tracked, but files can't be stored or
downloaded (the UI warns up front).

### Optional — throughput & testing

`EHI_POLL_SCHEDULE`, `EHI_MAX_IN_FLIGHT`, `EHI_START_PER_TICK` — see
[the performance section](#performance-batching--configurability).

`EHI_FORCE_FAILURE` — set to `true` to make every export fail on purpose, for
exercising the failure UI. Remove to restore normal behavior.

---

## Security & data

- All API endpoints require a **staff session** (`StaffSessionAuthMixin`); these
  surfaces expose full patient records.
- Runs are attributed to the logged-in staff member (`canvas-logged-in-user-id`).
- Custom data (namespace `msf__ehi_exports`) stores only **job metadata** — the
  patient reference, status, attempts, the bulkstatus file URLs, the S3 key, and
  who started it. The clinical content itself is **not** stored in custom data;
  it lives in your S3 bucket and is fetched on demand.
- Download links are short-lived **presigned** S3 URLs.

---

## Components

| Path | Role |
|------|------|
| `applications/ehi_app.py` | `Application` (scope `provider_menu_item`) that opens the workspace full-page. |
| `handlers/export_api.py` | Staff-only `SimpleAPI`: workspace, patient list, enqueue, status, download, runs. |
| `handlers/export_poller.py` | `CronTask` engine: starts queued jobs (throttled), advances, prepares to S3. |
| `services/export_jobs.py` | `ExportJob` persistence, queue/aggregation queries, filters. |
| `services/preparation.py` | Merge a patient's NDJSON → grouped Bundle → S3. |
| `services/storage.py` | S3 wrapper (`ExportStorage`) over the SDK S3 client. |
| `utils/fhir_client.py` | `EHIExportClient` — bulk-export operations on top of `CanvasFhir`. |
| `models/export_job.py` | `ExportJob` CustomModel + `CustomPatient` / `CustomStaff` proxies. |
| `templates/` | The workspace UI (`index.html`, `styles.css`, `main.js`). |

---

## Installation

```bash
canvas install ehi_export_tool --host <your-host>
```

Then set the variables above on the plugin configuration page.

## Testing

```bash
pytest
```

---

## Notes & limits

- "Re-run failed" and the run's failed-patient list handle up to 500 patients
  per action; click again for more.
- The export content is whatever Canvas includes in the EHI `$export` for a
  patient; the plugin groups and packages it but does not add or filter
  clinical data.
