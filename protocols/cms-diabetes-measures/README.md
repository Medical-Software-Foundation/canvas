# cms-diabetes-measures

Bundle of four CMS Clinical Quality Measures for adult diabetes care, ported from the legacy
`workflow_sdk_loader.builtin_cqms` package to the Canvas SDK plugin layout.

## Included protocols

| Class | Identifier | Title |
|---|---|---|
| `ClinicalQualityMeasure122v6` | CMS122v6 | Diabetes: Hemoglobin HbA1c Poor Control (>9%) |
| `ClinicalQualityMeasure123v6` | CMS123v6 | Diabetes: Foot Exam |
| `ClinicalQualityMeasure131v6` | CMS131v6 | Diabetes: Eye Exam |
| `ClinicalQualityMeasure134v6` | CMS134v6 | Diabetes: Medical Attention for Nephropathy |

The four protocols share an abstract base, `DiabetesQualityMeasure`, in
`protocols/diabetes_quality_measure.py`. All four measures apply to non-hospice patients
aged 18-75 with an active diabetes diagnosis during the measurement period.

## Behavior

Each protocol responds to a relevant data-change event, recomputes its denominator and
numerator over the most recent year, and emits a `ProtocolCard` effect describing whether
the patient is `SATISFIED`, `DUE`, or `NOT_APPLICABLE`. When a measure is unsatisfied the
card includes a recommendation (e.g. "Order HbA1c", "Conduct comprehensive foot exam",
"Refer for retinal examination", "Order a urine microalbumin test") that the clinician can
act on directly from the card.

## Notes on the port

- The legacy `compute_results() -> ProtocolResult` flow is replaced by
  `compute() -> list[Effect]` returning a single `ProtocolCard` effect per invocation.
- The legacy `ExternallyAwareClinicalQualityMeasure` mixin used by CMS122v6 and CMS131v6
  has no SDK equivalent. Those classes now inherit only from the in-plugin
  `DiabetesQualityMeasure` base. External-data awareness can be added by overriding the
  numerator/denominator methods.
- Value sets that exist in `canvas_sdk.value_set.v2022` are reused directly. Value sets
  that did not survive the migration (`VisualExamOfFoot`, `SensoryExamOfFoot`,
  `PulseExamOfFoot`, the amputation laterality sets, `AceInhibitors`, and
  `CMS134v6Dialysis`) are reproduced as in-plugin `ValueSet` subclasses with the original
  codes copied verbatim from `canvas_workflow_kit.value_set.v2018`,
  `medication_class_path2018`, and `specials`.
- `FundusPhotography` from CMS131v6 is reproduced in
  `protocols/cms131v6_diabetes_eye_exam.py` (single CPT code 92250).
- CMS123v6's numerator (three SNOMED foot-exam findings within the year) is preserved
  via `canvas_sdk.v1.data.questionnaire.Interview`. The legacy
  `patient.interviews.find_question_response(VisualExamOfFoot)` is rewritten as
  `Interview.objects.for_patient(...).committed().filter(interview_responses__response_option__code__in=codes, ...)`,
  which matches the same semantics: an interview qualifies when any
  `InterviewQuestionResponse` row points at a `ResponseOption` whose `code` is in the
  value set. The SDK's `Interview` queryset has no `find(value_set)` shortcut, so the
  value set is flattened to its code values inline.
- CMS134v6's "instruction" check (DialysisEducation) reads
  `canvas_sdk.v1.data.instruction.Instruction`, filtering on the related
  `note.datetime_of_service` to match the legacy `noteTimestamp` semantics. All
  six numerator pathways (dialysis referral, ACE inhibitor active medication,
  dismissing condition, kidney transplant, dialysis-education instruction, urine
  protein lab) are preserved.

## Tests

`tests/test_cms122v6.py` through `tests/test_cms134v6.py` exercise each protocol with
unit-level mocking of the SDK ORM querysets (`Condition.objects`, `Medication.objects`,
`LabReport.objects`, `ReferralReport.objects`). Run with:

```bash
PYTHONPATH="/Users/beau/p/canvas-plugins:$PYTHONPATH" \
  uv run --project /Users/beau/p/canvas-plugins pytest tests/ -v
```
