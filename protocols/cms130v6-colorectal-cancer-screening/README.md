# CMS130v15 Colorectal Cancer Screening

A Canvas SDK plugin that implements [CMS130v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0130v15), the eCQM for colorectal cancer screening in the 2027 performance period. The measurement period is the year ending now.

## What it does

Surfaces a protocol card recommending colorectal cancer screening for adults who have not had appropriate screening, and marks the card satisfied for patients with a qualifying exam in its look-back window.

### Initial population

- Adults 46-75 years of age at the end of the measurement period.
- A qualifying visit during the period (office, telephone, virtual, home health, annual wellness, or preventive care visit).

### Qualifying exams

| Exam | Window |
| --- | --- |
| FOBT, with a result | the measurement period |
| Stool DNA with FIT, with a result | the period and the 2 years before it |
| Flexible sigmoidoscopy | the period and the 4 years before it |
| CT colonography | the period and the 4 years before it |
| Colonoscopy | the period and the 9 years before it |

Lab tests come from lab values. Procedures and diagnostic studies come from referral reports, imaging reports, procedures, and billing line items. When several exams qualify, the card reports the one whose window lasts longest.

### Exclusions

- A diagnosis or history of colorectal cancer, or a total colectomy, on or before the end of the period, resolved or not.
- Hospice, palliative care, age 66+ living long term in a nursing home, or age 66+ with frailty and an advanced illness or dementia medication (`protocols/ecqm_common.py`).

### Card

Due patients get five recommendations: order a FOBT, an sDNA FIT test, a flexible sigmoidoscopy, a CT colonography, or a colonoscopy.

## Value sets

All value sets come from `canvas_sdk.value_set.v2027`, which ships in the SDK release containing [canvas-plugins#2003](https://github.com/canvas-medical/canvas-plugins/pull/2003).

## Shared code

`protocols/ecqm_common.py` and `tests/records.py` are identical copies shared with the other eCQM plugins, since plugins cannot import from one another. A test fails when the copies drift.

## Tests

Tests build real records in the SDK's test database through `pytest-canvas`:

```bash
CP=/path/to/canvas-plugins
uv run --frozen --project $CP --with-editable $CP --with-editable $CP/pytest-canvas pytest tests -q
```
