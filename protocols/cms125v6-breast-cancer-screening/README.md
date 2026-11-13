# CMS125v15 Breast Cancer Screening

A Canvas SDK plugin that implements [CMS125v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0125v15), the eCQM for breast cancer screening in the 2027 performance period. The measurement period is the year ending now.

## What it does

On each billing line item, condition, imaging report, instruction, interview, medication, or patient event, the plugin recomputes whether the patient is due for a screening mammogram and emits a protocol card.

### Initial population

- Women 42-74 years of age at the end of the measurement period.
- A qualifying visit during the period (office, telephone, virtual, home health, annual wellness, or preventive care visit).

### Exclusions

- A bilateral mastectomy (procedure or history diagnosis).
- Evidence of both a right and a left mastectomy, each side shown by a status-post diagnosis or a unilateral mastectomy procedure for that side. A unilateral mastectomy coded without a side does not count toward either side, because Canvas procedures carry no body site.
- Hospice, palliative care, age 66+ living long term in a nursing home, or age 66+ with frailty and an advanced illness or dementia medication (`protocols/ecqm_common.py`).

### Numerator

- A mammogram (imaging report) from October 1 two years before the period through its end: 27 months in all.

### Card

Due patients get an `Instruct` recommendation, "Discuss breast cancer screening and order imaging as appropriate". Satisfied cards name the most recent mammogram.

## Value sets

All value sets come from `canvas_sdk.value_set.v2027`, which ships in the SDK release containing [canvas-plugins#2003](https://github.com/canvas-medical/canvas-plugins/pull/2003).

## Shared code

`protocols/ecqm_common.py` and `tests/records.py` are identical copies shared with the other eCQM plugins (`cms-diabetes-measures`, `cms130v6-colorectal-cancer-screening`, `cms138v6-...`), since plugins cannot import from one another. A test fails when the copies drift.

## Tests

Tests build real records in the SDK's test database through `pytest-canvas`:

```bash
CP=/path/to/canvas-plugins
uv run --frozen --project $CP --with-editable $CP --with-editable $CP/pytest-canvas pytest tests -q
```
