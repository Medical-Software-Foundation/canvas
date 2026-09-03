# CMS130v6 Colorectal Cancer Screening

Self-contained Canvas SDK port of the legacy `CMS130v6` clinical quality measure.

## What it does

Surfaces a Protocol Card recommending colorectal cancer screening for adults 50-75 who have not had appropriate screening, and marks the card satisfied for patients who already have a qualifying exam within the relevant look-back window.

### Qualifying exams and look-back windows

| Exam                    | Look-back  |
| ----------------------- | ---------- |
| FOBT                    | 1 year     |
| FIT-DNA                 | 3 years    |
| Flexible sigmoidoscopy  | 5 years    |
| CT Colonography         | 5 years    |
| Colonoscopy             | 10 years   |

### Exclusions

Patients with an active diagnosis or past history of total colectomy or malignant neoplasm of the colon are excluded from the denominator.

## Recommendations

When a patient is due, the card surfaces five recommendations: order FOBT, order FIT-DNA, order Flexible sigmoidoscopy, order CT Colonography, or order Colonoscopy. The shared diagnostic context is ICD-10 `Z12.11` (Encounter for screening for malignant neoplasm of colon).

## Value sets

Most CMS130v6 value sets ship with the Canvas SDK (`canvas_sdk.value_set.v2022.*`). The supplementary LOINC code `79101-2` for CT Colonography is not in the v2018/v2022 packages, so this plugin defines a small local `CMS130v6CtColonography` ValueSet that combines with the SDK's `CtColonography` via the `|` operator.

## Caveats

The legacy CQM's `period_adjustment` (ProtocolOverride-driven custom cycle length) is not yet wired through to this SDK port; the look-back windows are fixed at the eCQM specification values.

## References

- [eCQI: CMS130v6 specification](https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS130v6.html)
- American Cancer Society. 2015. *Cancer Prevention & Early Detection Facts & Figures 2015-2016*.
- National Cancer Institute. 2015. *SEER Stat Fact Sheets: Colon and Rectum Cancer*.
- USPSTF. 2008. *Screening for colorectal cancer: U.S. Preventive Services Task Force recommendation statement*. Ann Intern Med 149(9):627-37.
