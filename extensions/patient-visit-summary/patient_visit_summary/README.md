# Patient Visit Summary

## Description

A Canvas plugin that generates a patient visit summary from a clinical note. It
offers two surfaces:

- **Patient Visit Summary** — a "Patient Visit Summary" button in the note
  **header** opens a modal with a formatted, print-ready HTML summary of the
  visit (with a print/save-as-PDF button).
- **Customize & Print** — a "Customize & Print" button in the note **footer**
  opens a panel where the provider can toggle/reorder sections, add header and
  footer text, and generate a finalized PDF that is attached to the patient's
  chart as a FHIR `DocumentReference`.

## Problem it solves

Practices that hand patients an after-visit summary — or that need a clean,
printable record of what happened at a visit — don't get a patient-friendly
printout from Canvas's clinician-oriented note view out of the box. The common
workaround is to copy the note's contents into a Word or Google doc, re-format
it by hand every time, and print from there, which is slow and invites
transcription errors and omissions. This plugin builds a formatted, print-ready
visit summary directly from the note's structured data in one click, and can
optionally produce a finalized PDF that is attached back to the chart as a FHIR
`DocumentReference` — no manual re-keying.

## Who it's for

Any practice that provides patients with an after-visit summary or printed visit
documentation. The summary mirrors the SOAP structure and covers both primary
care and specialty workflows (vitals, conditions, medications, orders,
immunizations, procedures, goals, follow-up, and billed services), so it is
specialty-agnostic. The primary users are providers and the clinical or
administrative staff who finalize and print visit documentation.

## Screenshots

> Screenshots use synthetic data on a development instance.

**Patient Visit Summary button (note header)**

![Patient Visit Summary button in the note header](docs/screenshots/01-patient-visit-summary-button.png)

**Rendered visit summary**

![Print-ready patient visit summary](docs/screenshots/02-visit-summary.png)

The print-ready summary modal, with a header logo/org block, a patient/visit
detail table, and the SOAP-organized content below. The **Print** button sends
it to the browser print / save-as-PDF dialog.

**Customize & Print button (note footer)**

![Customize & Print button in the note footer](docs/screenshots/03-customize-print-button.png)

**Customize & Print panel**

![Customize Note Print panel](docs/screenshots/04-customize-print-panel.png)

The customize panel: toggle and reorder sections, add optional header/footer
text, preview, and generate the finalized PDF that is attached to the chart.

## How It Works

The plugin declares four components in `CANVAS_MANIFEST.json`:

1. **`PatientVisitSummaryButton`** (`protocols/patient_visit_summary.py`) — note-header
   `ActionButton` that launches the summary modal.
2. **`PatientVisitSummaryAPI`** (`protocols/patient_visit_summary.py`) — SimpleAPI that
   fetches the note's clinical data (via `services/note_data_extractor.py`) and
   renders `templates/patient_visit_summary.html`.
3. **`CustomizePrintButton`** (`protocols/customize_print.py`) — note-footer
   `ActionButton` that launches the customize/print panel.
4. **`CustomizePrintAPI`** (`protocols/customize_print.py`) — SimpleAPI that renders the
   customize UI, persists the selection to the `CustomizedNotePrint` custom
   model, generates the PDF, and creates the FHIR `DocumentReference`.

Both SimpleAPIs authenticate via Canvas staff session credentials, with a shared
API key (`simple-api-key`) as a fallback (constant-time compared). Endpoints
address notes and finalized prints by their external **UUIDs**, never the
internal sequential `dbid`.

## What's Included in the Summary

The summary is organized into the following sections, mirroring the SOAP note structure:

**Subjective**
- Reason for Visit (with optional comment)
- History of Present Illness
- Review of Systems (with comments on individual answers when present)
- Questionnaires (with comments on individual answers when present)

**Objective**
- Vitals (height, weight with BMI, waist circumference, temperature with site, blood pressure with position/site, pulse rate with rhythm, respiration rate, oxygen saturation, notes)
- Physical Examination (with comments on individual answers when present)

**Assessment**
- Conditions Assessed (with background, status, and narrative)
- New Diagnoses (including diagnoses from structured assessments and coding gaps with ICD-10 codes)
- Resolved Conditions
- Changed Conditions
- Lab Results Review
- Imaging Review
- Consult Report Review
- Uncategorized Document Review
- Structured Assessments (with comments on individual answers when present)

**Plan**
- Plan narrative
- Prescriptions, Refills, Adjusted Prescriptions, Changed Medications, Stopped Medications
- Referrals (with contact information)
- Lab Orders and Imaging Orders
- Instructions
- Educational Materials
- Goals, Goal Updates, and Closed Goals

**Procedures**
- Immunizations administered (with CPT and CVX codes)
- Procedures performed (with CPT codes)

**History**
- Allergies (added and removed)
- Medication Statements
- Immunization Statements (with CPT and CVX codes)
- Family History
- Past Medical History
- Past Surgical History

**Next Steps**
- Follow-Up scheduling details (displayed as a separate top-level section)

**Billed Services**
- Active billing line items for the visit, shown patient-friendly: CPT code
  (with any modifiers, e.g. `90686-25`), description, and units — no charge
  amounts.

> CPT/CVX codes on immunizations and procedures are read from each command's
> structured `extra.coding` list; imaging orders display the CPT inline in the
> order title. The Billed Services section is sourced separately from the note's
> active `BillingLineItem` records.

The document closes with the provider's signature block including their name, credentials, NPI number, and organization contact information.

## How to install

From the plugin directory:

```bash
canvas install patient_visit_summary
```

Then set the plugin variables (see **Configuration (Variables)** below). Once
installed, two buttons appear on the note: **Patient Visit Summary** in the note
header and **Customize & Print** in the note footer.

> Note: the `CustomizedNotePrint` custom model includes a non-enumerable `uuid`
> column. If you are upgrading from a build that predates it, reinstall the
> plugin so the new column is provisioned.

## Configuration (Variables)

The plugin declares three sensitive variables in `CANVAS_MANIFEST.json` (modern
`variables` array). Set their values per-installation from the plugin's config
page or via the CLI:

| Variable | Purpose |
|----------|---------|
| `simple-api-key` | Fallback API-key auth for requests outside a staff session |
| `fhir-client-id` | OAuth client id used to create the FHIR `DocumentReference` (Customize & Print) |
| `fhir-client-secret` | OAuth client secret for the same |

If `fhir-client-id` / `fhir-client-secret` are not set, Customize & Print still
generates and stores the PDF locally — it just skips the FHIR
`DocumentReference` upload.

### Setting variables

1. Generate a secure random key for `simple-api-key`:

```bash
uv run python -c "import secrets; print(secrets.token_hex(16))"
```

2. Set values on your Canvas instance:

```bash
canvas config set PLUGIN_NAME simple-api-key=YOUR_GENERATED_KEY
canvas config set PLUGIN_NAME fhir-client-id=YOUR_FHIR_CLIENT_ID
canvas config set PLUGIN_NAME fhir-client-secret=YOUR_FHIR_CLIENT_SECRET
```

When calling the API outside a Canvas staff session, send the key in the
`Authorization` header:

```
Authorization: YOUR_GENERATED_KEY
```

## Customization

- **Logos**: The header displays two logo images (left and right) that are stored as base64-encoded strings in `images/images_b64.py`. Replace these with your organization's logos.
- **Organization Info**: The provider signature block at the bottom of the summary contains hard-coded organization contact information in the `index` method. Update this to match your organization.
- **Styling**: The summary's appearance is controlled by `templates/style.css`.
