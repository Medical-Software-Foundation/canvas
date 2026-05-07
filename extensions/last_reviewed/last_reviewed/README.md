# Last Reviewed

A patient chart summary section that shows, at a glance, when each chart
section was last marked as reviewed and by whom.

![Last Reviewed section in the patient chart summary](./Screenshot.png)

## What it does

Adds a custom **Last Reviewed** section pinned to the top of the patient
chart summary. For each chart section that supports Canvas's "Mark as
Reviewed" button, it reports:

- when the section was last marked reviewed (relative time, with the
  absolute timestamp on hover)
- the reviewing staff member's name
- "Never reviewed" if no review has been recorded for this patient

The six covered sections — the ones Canvas's `ChartSectionReviewCommand`
exposes — are: Conditions, Medications, Allergies, Immunizations,
Surgical History, Family History.

If a clinician marks a section reviewed by accident and then deletes the
review, the section automatically rolls back to whatever the previous
valid review was (or "Never reviewed" if none) — see *Filtering deleted
reviews* below.

## The problem this solves

Clinicians rely on the patient chart summary to make care decisions, but
the rows inside each section do not reflect whether the information is
considered current. Canvas exposes a *Mark as reviewed* button on each
section, but the history of those reviews is buried inside individual
notes — there's no single place to see when each section was last
reviewed and by whom. This plugin surfaces that history as a
top-of-summary section so the review status of every chart section is
visible at a glance.

## Who it's for

- Clinicians who own a panel of patients and need to know which
  sections have been reviewed recently before relying on them in a
  visit.
- Visiting or covering providers who are seeing a chart for the first
  time and want a quick read on how stale each section's contents
  might be.
- Ops or quality teams auditing review compliance across patients.

## How to install

Standard Canvas plugin install, run from the repository's `extensions/`
directory:

```bash
canvas install --host <your-instance> last_reviewed
```

No secrets, environment variables, or external API keys are required —
the plugin only reads internal Canvas chart-section-review commands.

The only configurable surface is **section ordering**. The plugin pins
its custom section to the top of the chart summary and lists the
default chart sections underneath in their default order; if another
plugin also emits a `PatientChartSummaryConfiguration` for the same
patient, the last-applied configuration wins (see *Caveat: section
ordering* below). To change the order, edit the `sections` list in
`handlers/section_config.py`.

## How it works

Two handlers, both responding to chart-summary events:

- `handlers/section_config.py` registers a
  `CustomSection("last_reviewed_summary")` in
  `PatientChartSummaryConfiguration` so Canvas knows to ask for the
  section's content.
- `handlers/section_content.py` queries the `Command` model for the
  most recent valid `chartSectionReview` per section, joins to the
  committer for the reviewer name, and returns a
  `PatientChartSummaryCustomSection` effect with HTML rendered from
  `static/section.html` and styles loaded from `static/section.css`.

Markup, styling, and a small client-side script live as separate files
under `static/`:

- `static/section.html` — Django template for the section body
- `static/section.css` — visual styles (font, weight, color hierarchy,
  icon size) tuned to match native chart sections
- `static/section.js` — toggles a `.lr-section--at-bottom` modifier
  class once the user has scrolled to the end of the section so the
  bottom-fade overflow affordance can drop out

The custom section ships as a single inline content blob, so the CSS
and JS are loaded via `render_to_string` and inlined into the HTML at
render time rather than referenced by URL.

## Bottom-fade overflow affordance

When the section's contents extend below the host's chart-summary slot,
a sticky `::after` overlay on `.lr-section` paints a soft fade at the
bottom edge as a "more below" hint. Because the host owns the scroll
container (not us), the fade is implemented in two pieces: a CSS-only
sticky pseudo that always sits at the visible viewport bottom, and the
small `static/section.js` listener that finds the nearest scrolling
ancestor and toggles a modifier class so the fade goes away once the
section's bottom edge is fully in view.

## Filtering deleted reviews

Canvas's "Mark as reviewed" workflow commits the `chartSectionReview`
command into a small standalone note. When the clinician deletes the
review, **the `Command` row itself is not modified** — `state` stays
`'committed'`, `entered_in_error` stays null. The undo is realized by
transitioning the parent note to `NoteStates.DELETED`. So the right
invariant for "this review is in effect" is the parent note's current
state, not anything on the `Command` row. The handler's query
explicitly excludes `note__current_state__state=NoteStates.DELETED`
to honor rolled-back reviews.

## Caveat: section ordering

`PatientChartSummaryConfiguration` is all-or-nothing — emitting it
overrides the default chart summary section list. This plugin
therefore emits the full default order with the custom section pinned
to the top. If another plugin also emits a configuration for the same
patient (for example, `pediatric_patient_chart_customizations`), the
last-applied configuration wins. To combine plugins, edit the section
list in `section_config.py` to match your desired layout.
