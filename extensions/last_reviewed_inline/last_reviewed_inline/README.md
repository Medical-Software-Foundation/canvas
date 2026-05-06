# Last Reviewed (Inline)

Adds an inline **Last reviewed …** banner to the top of the **Conditions**
and **Medications** sections of the patient chart, sourced from committed
`chartSectionReview` commands. A sibling plugin to `last_reviewed`, which
shows the same information for all six chart sections in a top-of-summary
custom section.

## What it does

For each of the two sections that have a per-section chart event in the
SDK (Conditions, Medications), emits a `PatientChartGroup` effect whose
single `Group` carries the review summary in its `name`:

- `Last reviewed 2 hours ago by Jane Smith`
- `Last reviewed 2 hours ago` (when the reviewer can't be resolved)
- `Never reviewed` (when no in-effect review exists)

The banner pins to the top of the section via a high `priority` so it
sits above other grouping-plugin contributions (e.g. the
`High Risk Medications` group emitted by `high-risk-medications`).

## Why only two sections

`PatientChartGroup` is the SDK's only mechanism for injecting content
into an existing chart section, and the SDK only emits per-section
events for `PATIENT_CHART__CONDITIONS`, `PATIENT_CHART__MEDICATIONS`,
and `PATIENT_CHART__DETECTED_ISSUES`. The remaining "Mark as reviewed"
sections (Allergies, Immunizations, Surgical History, Family History)
have no per-section event and so cannot be reached this way. For full
coverage, install the sibling plugin `last_reviewed`.

## Why an empty group

`PatientChartGroup` is designed for re-bucketing a section's existing
items into named groups. We are using it as a section-level label
(`items=[]`, banner text in `name`) — a workaround, not the intended
pattern. The trade-offs are documented in commit history; the
short version:

- The renderer treats `name` as a label string regardless of intent.
- Other plugins (`high-risk-medications`) can produce empty groups too,
  so empty-items is a tolerated state in the contract.
- If Canvas later adds a proper per-section banner / annotation effect,
  this plugin should migrate to it.

## Filtering deleted reviews

Same invariant as the sibling plugin: Canvas's "delete review" workflow
does not mutate the `Command` row; it transitions the parent note to
`NoteStates.DELETED`. The query therefore excludes commands whose note
is currently deleted, so undoing an accidental review automatically
rolls the banner back to the prior valid review (or *Never reviewed*
if none).
