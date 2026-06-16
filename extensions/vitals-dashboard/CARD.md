# Vitals Dashboard

A cardiology-focused vitals capture surface and trend dashboard, built as a tab right in the patient chart.

## The problem

Canvas's built-in vitals command is too narrow for a cardiology day clinic: one blood-pressure position per command, no dry weight, no per-void urine output, and no structured way to capture edema. Cardiology workflows - orthostatic BP for syncope, dry-versus-current weight and urine output for CHF fluid management - end up scattered across free text, where they can't be trended or exported cleanly.

## What it does

Adds a **Vitals** tab to the patient chart where clinical staff can:

- Record standard and orthostatic blood pressure and heart rate across laying, sitting, and standing
- Capture current and dry weight, urine output with a running total, O2 saturation, respiration, temperature, pain score, and edema notes
- View recent vitals over 24 hours, 7, 30, or 90 days as tables and trend charts
- Carry the last session forward as defaults, and export to CSV or a print-ready report

Every measurement is also saved as a native record on the chart, so it flows into the chart-summary sidebar and document exports.

## Who it's for

Cardiology day-clinic staff - nurses, medical assistants, and providers - who routinely capture orthostatic vitals, weight trends, and urine output. Useful anywhere the standard vitals surface is too narrow: CHF, syncope, autonomic workups, and post-procedure observation.

## Good to know

- No secrets or external services to configure.
- The dashboard is the source of truth; the chart note and exported records are documentation generated from it.
- A measurement can be marked entered-in-error and excluded from trends while staying visible in the audit table.
