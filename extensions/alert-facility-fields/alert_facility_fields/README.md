# alert_facility_fields

A Canvas SDK plugin that adds an **Alert facility** Yes/No field to the **Medication Statement**, **Stop Medication**, **Prescribe**, **Adjust Prescription**, and **Refill** commands and blocks committing those commands until the field is set.

## Why

Healthcare teams routinely need to flag whether a medication change should trigger a notification to the patient's facility (skilled nursing facility, group home, school, etc.). Capturing this signal at the point of charting — and refusing to commit a medication command (Medication Statement, Stop Medication, Prescribe, Adjust Prescription, or Refill) without it — keeps the data consistent and makes downstream automation (alerting, reporting, integrations) trivial: the answer is on the command itself, not buried in free text.

## What it does

When a clinician opens or prints a note containing a Medication Statement, Stop Medication, Prescribe, Adjust Prescription, or Refill command, the plugin contributes one extra form field:

| Property | Value |
|---|---|
| Label | Alert facility |
| Type | Single-select dropdown |
| Options | Yes / No |
| Required | Yes — the command cannot be committed until a value is chosen |

The selected value is persisted as command metadata under the key `alert_facility` (value `"Yes"` or `"No"`). Any downstream consumer — a CPA-style workflow plugin, a FHIR exporter, a reporting job — can read the value via the SDK's command-metadata data layer:

```python
from canvas_sdk.v1.data.command import CommandMetadata

entry = CommandMetadata.objects.filter(
    command__id=command_uuid,
    key="alert_facility",
).first()
```

The field renders both in the in-command charting UI and on the printed note. The Canvas SDK omits the field from the printout when no value is stored.

## How it works

Two `BaseHandler` subclasses, both registered in `CANVAS_MANIFEST.json`:

### `AlertFacilityFormHandler`

Subscribes to `EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS`. On each event it inspects `event.context["schema_key"]`; for `medicationStatement`, `stopMedication`, `prescribe`, `adjustPrescription`, or `refill` it returns a `CommandMetadataCreateFormEffect` declaring the Alert facility field. The same effect is returned regardless of `event.context["purpose"]` (`"form"` for chart UI, `"print"` for the printout), so the field surfaces in both contexts.

### `AlertFacilityRequiredValidator`

Subscribes to `MEDICATION_STATEMENT_COMMAND__POST_VALIDATION`, `STOP_MEDICATION_COMMAND__POST_VALIDATION`, `PRESCRIBE_COMMAND__POST_VALIDATION`, `ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION`, and `REFILL_COMMAND__POST_VALIDATION`. On commit it reads the stored `alert_facility` metadata via `CommandMetadata.objects.filter(...)`. If the value is missing or blank it returns a `CommandValidationErrorEffect` with the message *"Alert Facility is a required field."* — the platform surfaces the error inline and refuses the commit until the user makes a choice.

## Demo

[Loom walkthrough](https://www.loom.com/share/80b5b115d70a4609a2aaa59cbf62307a) —
shows the Alert facility dropdown rendering on a Medication Statement command,
the validation error appearing when commit is attempted without a value, and
the command committing cleanly once a value is selected.

## Project layout

```
alert-facility-fields/                          # repo root
├── pyproject.toml
├── mypy.ini
├── tests/
│   └── test_alert_facility_form.py
└── alert_facility_fields/                      # plugin package
    ├── CANVAS_MANIFEST.json
    ├── README.md
    ├── __init__.py
    └── protocols/
        ├── __init__.py
        └── alert_facility_form.py              # both handlers live here
```

## Installation

Install the plugin onto a Canvas instance using the Canvas CLI:

```bash
uv run canvas install --host <your-instance> alert_facility_fields
```

`<your-instance>` is the section header from your `~/.canvas/credentials.ini`. The CLI reuploads on subsequent runs and the platform hot-reloads the plugin.

## Configuration

None. The plugin declares no secrets, no environment variables, and no scope — it consumes only the platform-supplied event context and writes to command metadata.

## Development

```bash
# install dev dependencies
uv sync

# run tests with coverage
uv run pytest --cov=alert_facility_fields --cov-report=term-missing --cov-branch

# type-check
uv run mypy --config-file=mypy.ini alert_facility_fields tests
```

## Behavior notes

- **Storage values vs. labels:** the SDK's `SELECT` field stores the literal option string. A user picking "Yes" persists the string `"Yes"`; "No" persists `"No"`. Plan accordingly when reading the metadata downstream.
- **Standalone single-command print:** Canvas's standalone command print views (e.g. `GET /api/MedicationStatement/{id}.html`) currently do not pass plugin-declared additional fields into the template context. This is a Canvas home-app limitation, not a plugin issue. **Note printing is unaffected** — the field renders correctly on full-note printouts.

## References

- [CommandMetadataCreateFormEffect](https://docs.canvasmedical.com/sdk/command-metadata-create-form-effect/)
- [Command Validation Effect](https://docs.canvasmedical.com/sdk/effect-command-validation/)
- [Canvas SDK overview](https://docs.canvasmedical.com/sdk/)
