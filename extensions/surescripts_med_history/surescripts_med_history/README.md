surescripts-med-history
=======================

## What it does

Automates Surescripts eligibility and medication history requests for upcoming
appointments, then surfaces what comes back in the chart so a provider can
reconcile it against the patient's active medications in one place.

Two daily crons request eligibility (08:00 UTC) and medication history
(11:00 UTC) for patients with appointments at configurable pre-appointment day
offsets. An **Rx History** action button on the chart's medications section
opens a modal that compares the returned history against active medications,
split into **New / Unresolved**, **Matched**, and **Dismissed**. Each unresolved
row can be added to the note as a `MedicationStatement` (resolved through FDB)
or dismissed. A **Surescripts Requests** provider menu item does the same in
bulk for a date range and a set of providers.

## Problem it solves

Surescripts medication history is one of the few reliable signals about what a
patient is actually filling, including prescriptions written elsewhere — but
without tooling it sits outside the charting workflow. Staff either skip it or
retype medications by hand during a visit.

This plugin closes that loop: it requests the data before the appointment so
it's there when the visit starts, does the comparison against active meds
automatically (RxNorm, NDC, description, and an NDC→RxNorm cross-reference via
FDB), and reduces reconciliation to a single click per medication. Dismissals
persist and auto-clear when a medication later matches or a newer fill arrives,
so the same rows don't come back every visit.

## Who it's for

Prescribers doing medication reconciliation at the point of care, and the care
managers and medical assistants who prepare charts ahead of a visit.
Non-prescribers are supported explicitly: the modal lets a user without an SPI
pick an SPI-registered provider to request on behalf of, since Surescripts
rejects requests from unregistered staff.

## How to install

```bash
canvas install extensions/surescripts_med_history/surescripts_med_history --host <instance>
```

Requires Canvas SDK `0.142.0` or later, and a Surescripts-enabled instance —
providers must have an `spi_number` for requests to be accepted.

## Configuration options

Set these plugin secrets in the Canvas admin:

- **`namespace_read_write_access_key`** (required) — for the
  `medication__history` custom-data namespace where dismissals are stored.
  Without it, dismissals cannot be written or read.
- **`pre_appointment_days`** (optional) — comma-separated non-negative day
  offsets controlling which upcoming appointments the daily crons target.
  Default `"1,7"` (T+1 and T+7). `"0,3,7"` also includes same-day appointments.
  Malformed values fall back to the default and log a warning.
- **`commit_medication_statements`** (optional) — whether `+ Add` commits the
  `MedicationStatement` command or leaves it staged in the note for the provider
  to review. Default `"false"` (staged). Accepts `"true"`, `"committed"`,
  `"yes"`, `"1"`.
- **`mock_history_data`** (optional, demo only) — set to `"true"` to inject five
  fake medication-history rows so the workflow can be shown on an instance with
  no real Surescripts data. Rows are labeled **Test data** in the UI and run
  through the same matching, grouping, and dismissal logic as real rows.
  Because they carry real RxNorm/NDC codes, `+ Add` originates a genuine
  `MedicationStatement`. Default `"false"` — leave it off in live clinical
  environments.
- **`simpleapi-api-key`** (optional) — only needed if another plugin will call
  the `/integration/dismissals` endpoints.

## Components

| Component | Type | Purpose |
| --------- | ---- | ------- |
| `EligibilityCronTask` | Cron (08:00 UTC) | Eligibility requests for upcoming appointments |
| `MedHistoryCronTask` | Cron (11:00 UTC) | Medication history requests for upcoming appointments |
| `MedHistoryActionButton` | Action button | **Rx History** in the chart medications section |
| `MedHistoryRequestApi` | SimpleAPI | Modal's request / refresh / dismiss / add endpoints |
| `BulkRequestsApi` | SimpleAPI | Bulk request endpoints and page |
| `DismissalsIntegrationApi` | SimpleAPI | API-key surface for other plugins |
| `BulkSurescriptsApp` | Application | **Surescripts Requests** provider menu item |

## Endpoints

| Route | Method | Purpose |
| ----- | ------ | ------- |
| `/routes/request` | POST | Manual single-patient medication history request |
| `/routes/history` | GET | Re-read the modal's data (manual refresh + polling) |
| `/routes/dismiss` | POST | Dismiss a medication group for a patient |
| `/routes/add-medication` | POST | Originate a `MedicationStatement` from a history row |
| `/bulk/page` | GET | Bulk-requests app HTML |
| `/bulk/appointments` | GET | List upcoming appointments by date range and providers |
| `/bulk/eligibility` | POST | Bulk eligibility requests |
| `/bulk/med-history` | POST | Bulk medication history requests |
| `/integration/dismissals` | GET, POST | Read/create dismissals from another plugin |

`/routes/*` and `/bulk/*` require an authenticated staff session.
`/integration/dismissals` is API-key authenticated via the `simpleapi-api-key`
secret, for server-to-server use.

## Notes on behavior

- **Requests are gated on SPI.** Patients whose provider has no `spi_number` are
  skipped, with one warning per provider per run.
- **Eligibility fires alongside med history** on manual requests. Medication
  history depends on the ISA-13 interchange control number the 271 eligibility
  response returns, so requesting history alone can silently return nothing.
- **Added medications are tagged.** Every `MedicationStatement` this plugin
  originates carries command metadata `data_source=surescripts`.
- **Note metadata.** `surescripts_<eligibility|med_history>_status` and `_at` are
  stamped on the appointment's note (or the patient's most recent open note for
  manual requests) at request time. Requests made when no open note exists are
  not stamped.
- **Auditing.** Staff-initiated requests are logged with a `Surescripts request:`
  prefix naming both the initiator and the provider whose SPI was used — they
  differ whenever someone requests on another provider's behalf:
  ```bash
  canvas logs --host <instance> --since 30m | grep "Surescripts request:"
  ```

## Storage

Dismissals are persisted in a plugin-scoped `medication__history` `CustomModel`
namespace. No shared-namespace coupling and no schema-manager mirror required.

## Tests

```bash
uv run pytest
```

178 tests, 94% coverage.
