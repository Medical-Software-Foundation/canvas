# hospitalization-tracker

Track inpatient stays (ICU admissions, long stays) with structured data entry from a note tab and a live-updating chart summary section.

## What it does

- Adds an **"Add Hospitalization"** tab inside any Canvas note (NoteApplication)
- Providers fill in a form capturing: admission/discharge dates, hospital name, reason for admission, principal diagnosis, ICU stay (with duration), discharge disposition, treating physician, readmission within 30 days, and free-text notes
- On save, inserts an **"Inpatient Stay History"** CustomCommand into the note's History section showing the record just entered
- Displays all past hospitalizations in a **chart summary section** on the patient chart, with real-time WebSocket updates whenever a new record is added

## Components

| Component | Class | Purpose |
|-----------|-------|---------|
| NoteApplication | `HospitalizationTrackerApp` | "Add Hospitalization" tab in notes |
| SimpleAPI | `HospitalizationAPI` | Serves form HTML, creates records, renders chart section |
| WebSocketAPI | `HospitalizationWebSocket` | Authenticates WS connections for live section refresh |
| ChartSummarySection | `HospitalizationSummarySection` | Renders the Inpatient Stay History section |
| ChartSummaryConfig | `HospitalizationChartSummaryConfig` | Registers the section in the chart summary layout |
| CustomCommand | `HospitalizationSummary` | Read-only note entry for a single hospitalization |

## Custom Data

Namespace: `msf__hospitalization_tracker`

Records are stored in a `Hospitalization` CustomModel with fields: `patient`, `admission_date`, `discharge_date`, `hospital_name`, `reason_for_admission`, `principal_diagnosis`, `icu_stay`, `icu_duration_days`, `discharge_disposition`, `readmission_within_30_days`, `treating_physician`, `notes`.

## Configuration

### Required secrets

| Secret | Description |
|--------|-------------|
| `namespace_read_write_access_key` | Grants the plugin read/write access to the `msf__hospitalization_tracker` custom data namespace. Set this in Canvas admin after installing. |

## Installation

1. Install the plugin via `canvas install`
2. In Canvas admin, navigate to the plugin configuration and set the `namespace_read_write_access_key` secret
3. The "Add Hospitalization" tab will appear in all notes; the "Inpatient Stay History" section will appear in patient chart summaries
