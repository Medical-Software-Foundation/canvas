# patient_vitals

Adds a "My Vitals" page to the Canvas patient portal. Surfaces all vital signs
stored for the logged-in patient, with one tile per vital type and a trend chart
when more than one reading exists.

![My Vitals on the patient portal](../vitals.png)

## What it shows

For each distinct vital type with at least one reading:

- Inline SVG icon
- Latest value + unit (e.g. `120/80 mmHg`)
- Recorded date
- A "View trends →" affordance when there are 2+ readings

Clicking a multi-reading tile opens a modal with a Chart.js line graph. Blood
pressure renders as two series (systolic / diastolic) on one X axis.

## Architecture

Single `portal_menu_item` application + single `SimpleAPI` protocol.

- `patient_vitals.application:VitalsApp` — menu entry, opens the page modal.
- `patient_vitals.api:VitalsAPI` — two routes:
  - `GET /plugin-io/api/patient_vitals/page` — HTML page.
  - `POST /plugin-io/api/patient_vitals/observations` — JSON; actions `list_summary` and `history`.
- `patient_vitals.vitals_data` — pure functions: catalog, aggregation, BP split, unit conversion.

Data comes from the SDK ORM (`canvas_sdk.v1.data.Observation`). There is no
FHIR client and no `CLIENT_ID`/`CLIENT_SECRET` requirement; this plugin is
stateless and has no secrets.

Chart.js is loaded from `https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js`.

## Vital types supported

| Vital | LOINC | Unit |
|---|---|---|
| Blood Pressure | 85354-9 | mmHg |
| Pulse | 8867-4 | bpm |
| Body Temperature | 8310-5 | °F |
| Weight | 29463-7 | lbs (stored as oz, converted server-side) |
| Height | 8302-2 | in |
| BMI | 39156-5 | — |
| Oxygen Saturation | 59408-5 | % |
| Respiration Rate | 9279-1 | bpm |
| Waist Circumference | 56086-2 | cm |
| Head Circumference | 9843-4 | cm |
| Pain Severity | 72514-3 | — |

## Limits

- Server-side cap of 100 readings per vital code (chart shows the 100 most
  recent).
- v1 supports the **combined-string** form of blood pressure
  (`Observation.value == "120/80"`). Component-based BP (separate systolic /
  diastolic `ObservationComponent` rows) is not handled.

## Security

- Authentication: `PatientSessionAuthMixin`. Only logged-in patients can hit
  the endpoints; staff sessions are rejected.
- Patient identity is taken from the `canvas-logged-in-user-id` request header
  (populated by the auth mixin). The plugin never reads `patient_id` from a
  request body, so a patient cannot read another patient's vitals by spoofing
  the body.

## Menu icon

`patient_vitals/assets/icon.png` is currently a placeholder copy of the
`portal-content` labs icon so the plugin installs cleanly. Replace it with a
heart-rate / vitals glyph (~96×96 PNG, transparent background) before shipping.

## Local development

```bash
cd /Users/miguelquintas/Documents/canvas/canvas-msf/extensions/patient_vitals
uv run pytest tests/ -v
uv run ruff check patient_vitals tests
uv run mypy patient_vitals
```

Install against a local Canvas instance with the standard plugin install path,
then log in to the patient portal and open "My Vitals" from the menu.
