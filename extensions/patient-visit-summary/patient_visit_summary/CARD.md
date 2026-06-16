# Patient Visit Summary

Turn any clinical note into a clean, print-ready visit summary - a patient-friendly handout in one click, or a fully customizable PDF that's saved back to the chart.

## The problem

Canvas's out-of-the-box note print is clinician-oriented and inflexible: it surfaces internal workflow fields, doesn't let staff control what's included, and the result isn't durably attached back to the chart. Practices end up with two recurring pain points - patients need a clean handout, and staff need a finalized, customizable record for legal, billing, audit, or portal distribution. The common workaround is copying the note into Word, reformatting by hand every visit, and printing from there.

## What it does

Adds two surfaces to the note:

- **Patient Visit Summary** - a button in the note header opens a formatted, print-ready summary built straight from the note's data. Internal clinical-workflow fields are filtered out automatically, so the patient sees only what's useful to them.
- **Customize & Print** - choose which sections to include, reorder them, add header, footer, or comment text, preview live, and generate a finalized PDF that's attached to the chart as a clinical document for later retrieval. Every saved version stays accessible for re-print.

![Print-ready patient visit summary](https://raw.githubusercontent.com/Medical-Software-Foundation/canvas/main/extensions/patient-visit-summary/patient_visit_summary/docs/screenshots/02-visit-summary.png)

![Customize & Print panel - toggle and reorder sections, add header and footer text, preview, and generate the PDF](https://raw.githubusercontent.com/Medical-Software-Foundation/canvas/main/extensions/patient-visit-summary/patient_visit_summary/docs/screenshots/04-customize-print-panel.png)

## Who it's for

Specialty-agnostic - the section coverage mirrors SOAP structure and works for primary care, behavioral health, and most specialty workflows. Three audiences benefit:

- **Providers** finalizing a visit - generate a clean chart PDF and hand the patient a friendly summary at checkout.
- **Clinical and administrative staff** who curate visit documentation for legal, billing, audit, or portal distribution.
- **Plugin authors** building custom commands - their content is surfaced automatically, no coordination required.

## Good to know

- The patient-facing summary automatically strips internal clinical and billing workflow content.
- Finalized PDFs are attached back to the chart and retrievable later; previous versions are kept per note.
- Header logos are pulled from the practice location, so no plugin code changes are needed to brand the output.
