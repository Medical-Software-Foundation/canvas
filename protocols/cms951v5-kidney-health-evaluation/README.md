# cms951v5-kidney-health-evaluation

[CMS951v5](https://ecqi.healthit.gov/ecqm/ec/2027/cms0951v5) Kidney Health Evaluation, for the 2027 performance period, as a Canvas SDK protocol (`ClinicalQualityMeasure951v5`). The measurement period is the year ending now.

## Measure

Patients 18-85 at the start of the period with diabetes active at its start and an outpatient visit during it. The class extends `DiabetesQualityMeasure` (`protocols/diabetes_quality_measure.py`) and overrides its initial population.

The numerator is an eGFR and a urine albumin-creatinine ratio in the period, where a urine albumin and a urine creatinine within four days of each other also count. Only numeric results count (including comparator values such as `<3`). CKD stage 5 or end-stage renal disease excludes.

## Exclusions

`protocols/ecqm_common.py` implements the eCQM shared libraries HospiceQDM 7.0 and PalliativeCareQDM 6.0, which this measure applies, and documents how QDM data types map to Canvas records. The spec's inpatient discharge to hospice has no Canvas data to read.

Encounters match billing line items on both CPT and HCPCS codes directly, because `BillingLineItem.find()` reads only the `HCPCS` attribute while eCQM value sets carry `HCPCSLEVELII`.

## Value sets

All value sets come from `canvas_sdk.value_set.v2027`, which ships in the SDK release containing [canvas-plugins#2003](https://github.com/canvas-medical/canvas-plugins/pull/2003).

## Shared code

Plugins cannot import from one another, so each eCQM plugin carries identical copies of `protocols/ecqm_common.py` and `tests/records.py`, and each diabetes eCQM plugin (`cms122v6-diabetes-hemoglobin-a1c-poor-control`, `cms131v6-diabetes-eye-exam`, `cms951v5-kidney-health-evaluation`) carries an identical `protocols/diabetes_quality_measure.py`. Tests fail when the copies drift.

## Tests

Tests build real records in the SDK's test database through `pytest-canvas`:

```bash
CP=/path/to/canvas-plugins
uv run --frozen --project $CP --with-editable $CP --with-editable $CP/pytest-canvas pytest tests -q
```
