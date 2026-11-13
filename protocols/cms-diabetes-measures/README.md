# cms-diabetes-measures

Diabetes clinical quality measures for the 2027 performance period, as Canvas SDK protocols. The measurement period is the year ending now.

## Included protocols

| Class | Identifier | Title |
| --- | --- | --- |
| `ClinicalQualityMeasure122v6` | [CMS122v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0122v15) | Diabetes: Glycemic Status Assessment Greater Than 9% |
| `ClinicalQualityMeasure131v6` | [CMS131v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0131v15) | Diabetes: Eye Exam |
| `ClinicalQualityMeasure951v5` | [CMS951v5](https://ecqi.healthit.gov/ecqm/ec/2027/cms0951v5) | Kidney Health Evaluation |

CMS122 and CMS131 share `DiabetesQualityMeasure` (`protocols/diabetes_quality_measure.py`): patients 18-75 at the end of the period with diabetes overlapping it and a qualifying visit during it. CMS951 takes patients 18-85 at the start of the period with diabetes active at its start and an outpatient visit during it.

## Measures

- **CMS122v15** (inverse measure): the most recent HbA1c or glucose management indicator in the period is above 9.0%, has no result, or is missing. A numeric result wins over a more recent result without one; several numeric results on the most recent day take the lowest. A satisfied card means the patient is not in poor control. Due cards recommend ordering an HbA1c.
- **CMS131v15**: a retinal or dilated eye exam (referral reports and procedures) in the period, or in the year before it without diabetic retinopathy; an autonomous eye exam with a result; retinopathy severity findings for both eyes; or "no apparent retinopathy" findings in the year before. Autonomous exams and findings are coded questionnaire answers or observations. Bilateral anophthalmos excludes.
- **CMS951v5**: an eGFR and a urine albumin-creatinine ratio in the period, where a urine albumin and a urine creatinine within four days of each other also count. Only numeric results count (including comparator values such as `<3`). CKD stage 5 or end-stage renal disease excludes.

## Exclusions

`protocols/ecqm_common.py` implements the eCQM shared libraries HospiceQDM 7.0, PalliativeCareQDM 6.0, and AdvancedIllnessandFrailtyQDM 11.0, and documents how QDM data types map to Canvas records. CMS951 applies hospice and palliative care only; CMS122 and CMS131 apply all of them. Two spec criteria have no Canvas data to read: an inpatient discharge to hospice and a frailty device order.

Encounters match billing line items on both CPT and HCPCS codes directly, because `BillingLineItem.find()` reads only the `HCPCS` attribute while eCQM value sets carry `HCPCSLEVELII`.

## Value sets

All value sets come from `canvas_sdk.value_set.v2027`, which ships in the SDK release containing [canvas-plugins#2003](https://github.com/canvas-medical/canvas-plugins/pull/2003).

## Shared code

`protocols/ecqm_common.py` and `tests/records.py` are identical copies shared with `cms125v6-breast-cancer-screening`, `cms130v6-colorectal-cancer-screening`, and `cms138v6-...`, since plugins cannot import from one another. A test fails when the copies drift.

## Tests

Tests build real records in the SDK's test database through `pytest-canvas`:

```bash
CP=/path/to/canvas-plugins
uv run --frozen --project $CP --with-editable $CP --with-editable $CP/pytest-canvas pytest tests -q
```
