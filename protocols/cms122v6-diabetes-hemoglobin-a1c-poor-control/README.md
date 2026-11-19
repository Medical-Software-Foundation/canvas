# cms122v6-diabetes-hemoglobin-a1c-poor-control

[CMS122v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0122v15) Diabetes: Glycemic Status Assessment Greater Than 9%, for the 2027 performance period, as a Canvas SDK protocol (`ClinicalQualityMeasure122v6`). The measurement period is the year ending now.

## Measure

Patients 18-75 at the end of the period with diabetes overlapping it and a qualifying visit during it (`DiabetesQualityMeasure`, `protocols/diabetes_quality_measure.py`).

This is an inverse measure: the patient is in the numerator when the most recent HbA1c or glucose management indicator in the period is above 9.0%, has no result, or is missing. A numeric result wins over a more recent result without one; several numeric results on the most recent day take the lowest. A satisfied card means the patient is not in poor control. Due cards recommend ordering an HbA1c.

## Exclusions

`protocols/ecqm_common.py` implements the eCQM shared libraries HospiceQDM 7.0, PalliativeCareQDM 6.0, and AdvancedIllnessandFrailtyQDM 11.0, and documents how QDM data types map to Canvas records. Two spec criteria have no Canvas data to read: an inpatient discharge to hospice and a frailty device order.

Encounters match billing line items on both CPT and HCPCS codes directly, because `BillingLineItem.find()` reads only the `HCPCS` attribute while eCQM value sets carry `HCPCSLEVELII`.

## Value sets

All value sets come from `canvas_sdk.value_set.v2027`, which ships in the SDK release containing [canvas-plugins#2003](https://github.com/canvas-medical/canvas-plugins/pull/2003).

## Shared code

Plugins cannot import from one another, so each eCQM plugin carries identical copies of `protocols/ecqm_common.py` and `tests/records.py`, and each diabetes eCQM plugin (`cms122v6-diabetes-hemoglobin-a1c-poor-control`, `cms131v6-diabetes-eye-exam`, `cms951v5-kidney-health-evaluation`) carries an identical `protocols/diabetes_quality_measure.py`. Tests fail when the copies drift. The tests of `ecqm_common` itself live in this plugin.

## Tests

Tests build real records in the SDK's test database through `pytest-canvas`:

```bash
CP=/path/to/canvas-plugins
uv run --frozen --project $CP --with-editable $CP --with-editable $CP/pytest-canvas pytest tests -q
```
