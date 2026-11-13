# CMS138v15 Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention

A Canvas SDK plugin that implements [CMS138v15](https://ecqi.healthit.gov/ecqm/ec/2027/cms0138v15) for the 2027 performance period. The measurement period is the year ending now.

## Initial population

- Patients 12 or older at the start of the measurement period.
- At least two qualifying visits, or one preventive visit, during the period.
- Patients in hospice are excluded.

This is a three-population measure:

- **Population 1**: was the patient screened for tobacco use during the measurement period?
- **Population 2**: if the most recent screening identified a tobacco user, did the patient receive a cessation intervention during the period or the six months before it?
- **Population 3**: composite of Populations 1 and 2.

## Data

- Screenings are committed questionnaires coded in the Tobacco Use Screening value set; the result is the answer's response option code. Only the most recent screening in the period decides tobacco use status.
- Counseling is an instruction or procedure coded in the Tobacco Use Cessation Counseling value set, or a tobacco abuse counseling diagnosis (Z71.6) starting in the window.
- Pharmacotherapy is a cessation medication starting in the window.

## Card

| Patient state | Status | Recommendations |
| --- | --- | --- |
| Not in the initial population, or in hospice | `not_applicable` | none |
| No screening in the period | `due` | complete tobacco use questionnaire (`interview`) |
| Most recent screening: non-user | `satisfied` | none |
| Tobacco user with an intervention in the window | `satisfied` | none |
| Tobacco user without an intervention | `due` | cessation counseling (`instruct`) and cessation medication (`prescribe`) |

Recommendations open blank commands: the home-app GraphQL layer drops the `context` an SDK recommendation carries, so the clinician picks from the unfiltered instruction, medication, or questionnaire list.

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
