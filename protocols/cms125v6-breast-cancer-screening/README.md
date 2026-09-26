# CMS125v6 Breast Cancer Screening

A Canvas SDK plugin that implements [CMS125v6](https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS125v6.html), the eCQM for breast cancer screening.

## What it does

For every applicable event (`condition_*`, `imaging_report_*`, `patient_*`, `billing_line_item_*`), the plugin recomputes whether the patient is due for a screening mammogram and emits a protocol card.

### Population

- Women aged 51–74 at the end of the measurement period.

### Exclusions (denominator)

- Bilateral mastectomy.
- Two unilateral mastectomies.
- One unilateral mastectomy plus a Status-Post-Left-Mastectomy or Status-Post-Right-Mastectomy diagnosis.

### Numerator

- One or more mammograms (or breast tomosynthesis) in the measurement period or the 15 months prior to it.

### Recommendation

If the patient is in the denominator but not the numerator the plugin emits an `Instruct` recommendation titled "Discuss breast cancer screening and order imaging as appropriate".

## Value sets

This plugin depends on the SDK value sets `BilateralMastectomy`, `StatusPostLeftMastectomy`, `StatusPostRightMastectomy`, and `Mammography` from `canvas_sdk.value_set.v2022`. The combined `UnilateralMastectomy` value set and the `CMS125v6Tomography` LOINC code are defined inline in `protocols/cms125v6_breast_cancer_screening.py` because the SDK only ships the laterality-split versions.

## Tests

Unit tests live in `tests/`. They exercise the protocol logic by injecting fake `patient`, `conditions`, and `imaging_reports` collections without requiring a Django database.

```bash
PYTHONPATH=/path/to/canvas-plugins pytest tests/ -v
```
