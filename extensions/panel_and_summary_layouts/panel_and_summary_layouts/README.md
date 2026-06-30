panel_and_summary_layouts
=========================

Example plugin showing how to customize Canvas UI layouts using the Canvas
SDK's layout effects.

## What it demonstrates

Two `BaseHandler` event handlers, both in `handlers/event_handlers.py`:

### `PanelLayout`

Responds to `PANEL_SECTIONS_CONFIGURATION`. Returns a `PanelConfiguration`
effect that defines which sections appear (and in what order) in the side
panel. The same event fires for two different surfaces:

- **Global panel** — the panel shown outside of a patient chart.
- **Patient panel** — the panel shown inside a patient chart.

The two surfaces use different enum types (`PanelGlobalSection` vs
`PanelPatientSection`) and Canvas validates that the returned sections
match the surface the event fired for. To distinguish them, the handler
checks `event.target.id`: it's empty for the global panel and the patient
id for the patient panel.

Sections not included in the configured list are hidden. The order in the
list is preserved in the rendered panel; sections that don't fit in the
available space collapse into the panel's "..." overflow menu.

### `PatientSummaryLayout`

Responds to `PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION` and returns a
`PatientChartSummaryConfiguration` effect that reorders (and optionally
omits) sections in the patient chart summary.

## Customizing

Edit the four module-level constants in `handlers/event_handlers.py`:

- `HIDDEN_GLOBAL_SECTIONS` / `VISIBLE_GLOBAL_SECTIONS`
- `HIDDEN_PATIENT_SECTIONS` / `VISIBLE_PATIENT_SECTIONS`
- `PATIENT_SUMMARY_SECTION_ORDER`

The `HIDDEN_*` frozensets are documentation-only — only the `VISIBLE_*` and
`PATIENT_SUMMARY_SECTION_ORDER` lists are sent to Canvas. The tests assert
that the visible and hidden sets partition the full enum so a future enum
addition won't silently disappear from the panel.

## What this example hides / reorders

Out of the box, the example mirrors a real customer's configuration:

### Global panel

Hidden: Recall appointments, Outstanding referrals, Inpatient stays, Messages.
Order: Appointment, Task, Refill request, Change request, Lab report,
Imaging report, Referral report, Uncategorized document, Prescription alert.

### Patient panel

Hidden: Inpatient stays.
Order: Command (UI label: "Protocols"), Task, Refill request, Change
request, Lab report, Imaging report, Referral report, Uncategorized
document, Prescription alert.

### Patient chart summary

Hidden: Coding gaps.
Order: Goals, Care teams, Medications, Allergies, Vitals, Conditions,
Social determinants, Immunizations, Family history, Surgical history.

## Running tests

```
uv sync
uv run python -m pytest
uv run python -m mypy --config-file=mypy.ini .
```

The handlers do no I/O, so the tests are pure unit tests using
`unittest.mock.Mock` for the event object. Coverage is 100% on the handler
module.

## Notes

- `PanelConfiguration.apply()` only serializes `sections` into the effect
  payload — not `page`. The `page` argument is used for client-side
  validation that the section enum types match. Canvas applies the response
  to whichever surface fired the event, so the `event.target.id` branch is
  what actually scopes the patient vs global config.
- The patient panel enum (`PanelPatientSection`) does not include `MESSAGE`,
  so messaging cannot be hidden from the patient panel via this effect.
- Sections rendered as "Protocols" in the Canvas UI map to the `COMMAND`
  enum value in `PanelPatientSection`.
