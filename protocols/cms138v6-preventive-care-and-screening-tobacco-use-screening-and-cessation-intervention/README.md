# CMS138v6 - Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention

## Target Population

Patients aged 18 years and older who have either:

- Had at least one eligible preventive visit in the measurement period, or
- Had at least two other eligible encounters (office visit, home health,
  occupational/speech/hearing evaluation, psych visit, ophthalmologic services,
  or health & behavioral assessments) in the measurement period.

This protocol is a three-population CQM:

- **Population 1**: was the patient screened for tobacco use within 24 months?
- **Population 2**: if identified as a tobacco user, did the patient receive a
  cessation intervention (counseling or pharmacotherapy)?
- **Population 3**: composite of Populations 1 and 2.

## Recommendations

| Patient state                              | Card status      | Recommendation(s)                                       |
| ------------------------------------------ | ---------------- | ------------------------------------------------------- |
| Under 18                                   | `not_applicable` | (none)                                                  |
| No eligible visits                         | (no card)        | (none)                                                  |
| Eligible, current tobacco user, no Rx      | `due`            | `instruct` (cessation counseling) and `prescribe`       |
| Eligible, no screening on record           | `due`            | `interview` (tobacco use questionnaire)                 |
| Screened non-user                          | `satisfied`      | (none)                                                  |
| Tobacco user with counseling on file       | `satisfied`      | (none)                                                  |
| Tobacco user with cessation Rx on file     | `satisfied`      | (none)                                                  |

## Importance

The USPSTF gives tobacco screening and brief cessation intervention a Grade A
recommendation. Tobacco users who stop using tobacco lower their risk for heart
disease, lung disease, and stroke. This protocol surfaces gaps in either the
screening step or the follow-up intervention step.

## Source

Ported from `canvas_workflow_kit.builtin_cqms.cms138v6_preventive_care_and_screening_tobacco_use_screening_and_cessation_intervention.ClinicalQualityMeasure138v6`.

Measure spec: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html

## Gaps

The legacy workflow-kit protocol has direct access to in-memory record sets
(`patient.instructions`, `patient.interviews`, etc.) whose schema does not have
a clean 1:1 mapping in the Canvas SDK. The following gaps were introduced
during the port:

- The legacy `add_prescribe_recommendation` /
  `add_instruction_recommendation` / `add_interview_recommendation`
  helpers built a `command.filter.coding` payload that constrained the
  downstream command's picker to codes in the value set. The home-app
  GraphQL layer at
  [`home-app/api/graphql/protocol/types.py:99-105`](../../../api/graphql/protocol/types.py)
  distinguishes SDK recommendations from legacy ones by the absence of
  the legacy `rank` field and emits `ProtocolCommand(type=<command>)`
  with empty `fields`, bypassing the `_resolve_<command>` resolvers
  (e.g. `_resolve_instruct` at line 248, `_resolve_interview` at line
  174) that would otherwise turn `command.filter.coding` into populated
  fields. Anything passed as `context=` to
  `ProtocolCard.add_recommendation` is silently dropped at this layer.
  The recommendations therefore open blank prescribe / instruct /
  interview commands; the clinician picks from the unfiltered medication,
  instruction, or questionnaire list. Closing this gap requires updating
  the home-app GraphQL resolver to populate `ProtocolCommand.fields`
  from the SDK recommendation's `context` (or to dispatch through the
  same `_resolve_<command>` resolvers as legacy CQMs do).
- The `MedicalReason` denominator-exception path (the
  `assessment_not_performed` / `counseling_not_performed` /
  `medication_not_ordered` `cached_property` methods in the legacy source) is
  commented out in the original workflow kit and is **not ported**.
- `events.HEALTH_MAINTENANCE` does not exist in the SDK. The protocol
  responds to `PATIENT_CREATED`, `PATIENT_UPDATED`, `CONDITION_CREATED`,
  `MEDICATION_LIST_ITEM_CREATED`, `BILLING_LINE_ITEM_CREATED`,
  `INTERVIEW_CREATED`, `INSTRUCTION_CREATED`, and `INSTRUCTION_UPDATED`
  instead, which collectively cover the relevant data-change paths.
- The legacy `HealthBehavioralAssessmentIndividual`,
  `HealthAndBehavioralAssessmentInitial`, and
  `HealthAndBehavioralAssessmentReassessment` value sets only exist in
  `canvas_workflow_kit.value_set.v2018`; the SDK distribution does not ship
  them. They are re-declared inline in
  `protocols/cms138v6_tobacco_screening_and_cessation.py` (single CPT code
  each).
- The `TobaccoUser` and `TobaccoNonUser` value sets only exist in the SDK's
  `v2026.no_qdm_category_assigned`; the legacy protocol used the v2018
  versions. The codes are equivalent SNOMED CT concepts.
