# Quick Copy Patient Info

A patient chart summary section that pins the four most-copied patient
fields - **Name**, **Date of Birth**, **Phone**, and **Address** - to the
top of every patient chart, each with a one-click copy button.

## What it does

Adds a custom **Patient Info** section pinned to the top of the patient
chart summary, above all standard chart sections. For each populated
field, the section renders a row with a label, the value, and a small
copy button. Clicking the button writes the field's payload to the
clipboard and briefly swaps the button icon to a check mark.

- **Name** - patient's first and last name. Copies the same string that
  is displayed.
- **DOB** - patient's date of birth in `MM/DD/YYYY` format. Copies the
  same string.
- **Phone** - the patient's primary (lowest-rank) active phone number,
  displayed in NANP `(XXX) XXX-XXXX` format when the raw value parses as
  a 10-digit US number. The copy payload is digits-only
  (`5551234567`), which is friendlier to dialers, forms, and SMS
  recipients that re-format automatically.
- **Address** - the patient's home address (falls back to the first
  active address) in multi-line USPS format:

  ```
  123 Main St
  Apt 4
  Indianapolis, IN 46077
  ```

  Newlines are preserved in the copy payload so pasting into a message
  or label keeps the line breaks.

If a field is empty (no phone on file, no address, etc.), its row is
omitted entirely from the section - no placeholder, no greyed-out
"Not on file" text. The section keeps a compact footprint and only
shows what is actually available to copy.

## The problem this solves

Clinicians, MAs, and front-desk staff routinely copy patient
identifiers out of Canvas to paste into external messages, faxes,
pharmacy callbacks, dialers, and prior-authorization forms. The
existing path is multi-step: open Demographics, highlight the value,
copy it, scroll back. Doing that several times per call (name to a
Slack message, DOB to a pharmacy, phone to a dialer) adds up.

This plugin replaces that workflow with a one-click action at the very
top of the chart.

## Who it's for

- Providers, MAs, and care navigators who copy patient identifiers
  into Slack, email, or scribed notes during or after a visit.
- Front-desk staff who relay patient info to pharmacies, labs, and
  payors over the phone.
- Anyone who runs a lot of prior-auth or referral paperwork and
  pastes patient demographics into external forms.

## How to install

Standard Canvas plugin install, run from the repository's `extensions/`
directory:

```bash
canvas install --host <your-instance> quick_copy_patient_info
```

No secrets, environment variables, or external API keys are required -
the plugin only reads internal Canvas patient demographic data.

## How it works

Two handlers, both responding to chart-summary events:

- `handlers/section_config.py` registers a
  `CustomSection("quick_copy_patient_info")` in
  `PatientChartSummaryConfiguration` so Canvas knows to ask for the
  section's content. The section is listed first in the configuration
  so it pins to the top.
- `handlers/section_content.py` queries the `Patient` model via the
  Canvas SDK, formats the four fields, builds a row dict per populated
  field, and returns a `PatientChartSummaryCustomSection` effect with
  HTML rendered from `static/section.html`.

Markup, styling, and the client-side copy logic live as separate files
under `static/`:

- `static/section.html` - Django template for the section body and
  per-row copy buttons.
- `static/section.css` - visual styles tuned to match native chart
  sections (Lato, 14px, rgba color hierarchy).
- `static/section.js` - delegates clicks on `.qcpi-copy` buttons to
  `navigator.clipboard.writeText`, with a `document.execCommand`
  fallback for older embedded browsers.

The custom section ships as a single inline content blob, so the CSS
and JS are loaded via `render_to_string` and inlined into the HTML at
render time rather than referenced by URL.

## Field formatting rules

| Field | Display | Copy payload |
| --- | --- | --- |
| Name | `first_name last_name` | same as display |
| DOB | `MM/DD/YYYY` | same as display |
| Phone | `(555) 123-4567` (NANP), or raw value for non-NANP | digits only (`5551234567`) |
| Address | Multi-line USPS (line1, optional line2, "city, state postal_code") | same as display, newlines preserved |

Phone parsing strips all non-digits, accepts 11-digit numbers that
start with `1` by dropping the leading `1`, and falls back to showing
the raw value verbatim when the digit count doesn't match a US phone.
A row with no numeric digits at all is omitted entirely.

## Caveat: section ordering

`PatientChartSummaryConfiguration` is all-or-nothing - emitting it
overrides the default chart summary section list. This plugin
therefore emits the full default section list with the custom section
pinned to the top. If another plugin also emits a configuration for
the same patient (for example, `last_reviewed` or another summary
customization), the last-applied configuration wins. To combine
plugins, edit the section list in `handlers/section_config.py` to
match your desired layout.

## Privacy and security

The plugin reads patient PHI directly from the Canvas SDK ORM and
renders it into HTML that is served only inside the authenticated
Canvas chart UI. Nothing is sent to external services. The clipboard
write happens entirely in the user's browser via the standard
Async Clipboard API.

## Development

Run the tests from the plugin's outer directory:

```bash
cd extensions/quick_copy_patient_info
uv sync
uv run pytest
```
