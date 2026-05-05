# Last Reviewed

A patient chart summary section that shows, at a glance, when each chart
section was last marked as reviewed and by whom.

## What it does

Adds a custom **Last Reviewed** section to the top of the patient chart
summary. For each chart section that supports Canvas's "Mark as Reviewed"
button, it reports:

- when the section was last marked reviewed (relative time, with the absolute
  timestamp on hover)
- the reviewing staff member's name
- "Never reviewed" if no review has been recorded for this patient

The six covered sections — the ones the `ChartSectionReviewCommand` exposes —
are: Conditions, Medications, Allergies, Immunizations, Surgical History,
Family History.

## How it works

Each click of "Mark as Reviewed" commits a `ChartSectionReviewCommand`
(`schema_key="chartSectionReview"`) into the active note. The plugin queries
the `Command` model for the most recent committed, non-errored review per
section, joins to the committer, and renders a small HTML table that the
custom section effect injects into the chart summary.

Two handlers, both responding to chart-summary events:

- `handlers/section_config.py` registers a `CustomSection("last_reviewed_summary")`
  in `PatientChartSummaryConfiguration` so Canvas knows to ask for the
  section's content.
- `handlers/section_content.py` builds the row list and returns a
  `PatientChartSummaryCustomSection` effect with HTML rendered from
  `static/section.html`.

## Caveat: section ordering

`PatientChartSummaryConfiguration` is all-or-nothing — emitting it overrides
the default chart summary section list. This plugin therefore emits the full
default order with the custom section pinned to the top. If another plugin
also emits a configuration for the same patient (for example,
`pediatric_patient_chart_customizations`), the last-applied configuration
wins. To combine plugins, edit the section list in `section_config.py` to
match your desired layout.
