# vitals-dashboard

Cardiology vitals capture + dashboard as a Canvas full-chart tab.

## What it does

Adds a **Vitals** tab to the patient chart (`full_chart` application scope) that lets clinical staff:

- Record a standard BP + HR with cuff location, plus orthostatic BP/HR across laying / sitting / standing
- Record current + dry weight (lbs)
- Log one or more urine-output entries with running total
- Record O2 saturation, respiration rate, temperature, pain score, and edema note
- View the patient's recent vitals (24h / 7d / 30d / 90d / all) as tables and trend charts
- Carry forward the most recent finished session as defaults for a new session
- Export the view to CSV or a print-formatted report
- Mark a committed measurement as Entered-in-Error (excluded from this dashboard's
  trend charts, CSV, and Print Report; the row remains visible in the audit table
  with strikethrough. Note: retraction is dashboard-scoped — it does not propagate
  to the FHIR `Observation` already emitted to the chart-summary sidebar / CCDA
  export. To correct the chart-wide record, start a new session with the corrected
  values.)

Clicking **Finish Session** emits a Canvas `Vitals` note with a read-only `VitalsSummary` custom command summarizing the session, then immediately calls `POST /sync_observations`. That endpoint resolves the new note's dbid and emits native FHIR `Observation` records for every captured measurement so they appear on the chart-summary sidebar and in CCDA exports. The dashboard remains the source of truth; the note + Observations are documentation.

## Problem it solves

The built-in Canvas `VitalsCommand` is too limited for a cardiology day clinic: only one BP position per command, no dry weight, no per-void urine output, and no structured way to capture qualitative edema. Cardiology-relevant workflows (orthostatic BP for syncope / autonomic workups, dry vs. current weight + urine output for CHF fluid management) end up scattered across free-text. CCDA / USCDI export also requires native `Observation` records, which `CustomModel` rows alone cannot satisfy. This plugin provides a cardiology-specific capture surface and persists every measurement as a native `Observation`.

## Who it's for

Cardiology day-clinic clinical staff (nurses, medical assistants, and providers) who routinely capture orthostatic vitals, weight trends, and urine output. Useful anywhere the standard VitalsCommand surface is too narrow — CHF, syncope, autonomic dysfunction, post-procedure observation.

## How to install

```
canvas install vitals-dashboard
```

After install, enable the `vitals__dashboard` custom data namespace on the instance. The plugin also requires a `NoteType` named "Vitals" (case-insensitive match, with an `icontains` fallback) and at least one `PracticeLocation` and one `Staff` record. No secrets are needed.

## Components

| Kind | Class / Name | Purpose |
|---|---|---|
| Application | `vitals_dashboard.applications.vitals_dashboard:VitalsDashboardApp` | Renders the full-chart Vitals tab |
| Protocol (SimpleAPI) | `vitals_dashboard.api.vitals_api:VitalsAPI` | Read/write endpoints consumed by the tab, plus `/sync_observations` |
| Command | `VitalsSummary` (`schema_key: vitalsSummary`) | Read-only session summary embedded in the Vitals note |

## Events

- `SIMPLE_API_AUTHENTICATE` + `SIMPLE_API_REQUEST` — all tab reads/writes, including the post-finish observation sync.

## API endpoints

All routes are prefixed with `/plugin-io/api/vitals_dashboard`. Every route requires a logged-in **staff** session (enforced by `StaffSessionAuthMixin`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions` | Create or update a session + its measurements; optional `finish: true` emits the Vitals note |
| POST | `/sync_observations` | Resolve a finished session's note dbid and emit native FHIR `Observation` records for its measurements. Returns 503 `{retry: true}` if the note hasn't committed yet — client retries with backoff. |
| GET | `/sessions` | List recent sessions for a patient |
| GET | `/sessions/draft` | Most recent unfinished session + its measurements (auto-restore) |
| GET | `/sessions/last` | Most recent finished session + its measurements (carry-forward) |
| GET | `/measurements` | Measurements for a patient over a window (24h / 7d / 30d / 90d / all) |
| PATCH | `/measurements/<id>` | Edit a measurement; requires `patient_key` query param matching the record |
| DELETE | `/measurements/<id>` | Soft-delete a measurement; requires `patient_key` query param matching the record |
| GET | `/report_context` | Patient demographics + practice info for the Print Report header |

## Data model

The plugin stores its own tables via Canvas `CustomModel` under namespace `vitals__dashboard`:

- `VitalsSession` — one charting session per patient/note
- `VitalsMeasurement` — one measurement row (keyed by string `session_id`)

String ids (not FKs) are used for `patient_key`, `entered_by_staff_key`, `provider_of_record_key`, and `session_id`. Native FHIR `Observation` records are also persisted on Finish Session for CCDA / chart-summary visibility — `VitalsMeasurement` remains the dashboard's read source.

## Configuration options

No secrets, no external services. The instance must have:

- A `NoteType` named "Vitals" (case-insensitive match, with an `icontains` fallback)
- At least one `PracticeLocation`
- At least one `Staff` record
- The `vitals__dashboard` custom data namespace enabled

## Screenshots

<!-- TODO: Add at least one screenshot or short screen-recording link demonstrating the Vitals tab in use. -->

## Running tests

```
uv run pytest tests/
```
