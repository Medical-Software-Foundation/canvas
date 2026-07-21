# Sleep Screening

A note tab that appears on Sleep Intake visits and runs the three standard sleep screeners in one place: STOP-BANG (apnea risk), the Epworth Sleepiness Scale (daytime sleepiness), and the Insomnia Severity Index. Each screener scores itself at the point of care, commits to the note as a structured questionnaire result, and drives the next step - a staged diagnosis and a sleep-study task the clinician reviews and commits.

## What it does

- Adds a "Sleep Screening" tab to a note, shown only when the note's structured reason for visit matches the configured trigger code.
- Renders all three instruments in-app. STOP-BANG pre-fills Age, Sex, and BMI from the chart (BMI is derived from the latest committed height and weight; if either is missing, that point is omitted and noted).
- Scores each instrument live. When the provider saves an instrument, its questionnaire commits to the note and a structured score result is written.
- Offers a curated menu of common sleep-medicine ICD-10 codes, with provisional codes pre-checked for positive screens. Selected diagnoses are staged (not committed) for clinician review.
- Stages a sleep-study task (in-clinic PSG or at-home HSAT) assigned to the queue.
- On completion the tab returns focus to the note so the provider can review and commit the staged items.

## Problem it solves

Sleep practices screen nearly every patient with the same three validated instruments, and today those are scored by hand while ordering a study means bolting an order action onto a diagnosis. This plugin puts the three screeners in the note, scores them at the point of care, and turns a positive screen into a reviewed diagnosis and a sleep-study task, so the visit opens with risk already quantified and the next step one click away.

## Who it's for

Sleep-medicine clinicians and any provider who runs sleep screening during a visit. It is built for in-visit charting on trial and demo instances, so it never touches the Patient Portal.

## How to install

1. Install the plugin into your Canvas instance:
   ```bash
   canvas install --host <your-instance> /path/to/sleep_screening/sleep_screening
   ```
2. (Optional) Set the reason-for-visit trigger and diagnosis menu with `--variable`, or later via `canvas config set`:
   ```bash
   canvas config set sleep_screening RFV_TRIGGER_CODE=sleep-intake --host <your-instance>
   ```
3. Open a note whose structured reason for visit matches `RFV_TRIGGER_CODE` (default `sleep-intake`). The "Sleep Screening" tab appears on that note.

The three questionnaires install with the plugin, so they exist even if the instance has none configured.

## Screenshots or screen recordings

_Screenshots to be added._

## Scope

- No Patient Portal surface. Instruments are administered in-app during the visit.
- No visualizations and no custom commands.
- No auto-committed diagnoses. Every staged diagnosis is clinician-reviewed.

## Codings

STOP-BANG, Epworth, and ISI have no LOINC codes published (all three are copyrighted instruments). Questionnaire, question, response, and scoring-result codes are therefore INTERNAL with meaningful unique codes. Staged diagnoses use ICD-10 (the diagnose command accepts ICD-10 only). Screen-positive results suggest provisional or unspecified codes (e.g. R06.83 snoring, G47.30 sleep apnea unspecified, R40.0 somnolence, G47.00 insomnia unspecified), not confirmed-disorder codes, per ICD-10-CM outpatient coding rules.

## Configuration (secrets)

| Secret | Default | Purpose |
| --- | --- | --- |
| `RFV_TRIGGER_CODE` | `sleep-intake` | The reason-for-visit code that makes the tab appear. |
| `RFV_TRIGGER_SYSTEM` | `INTERNAL` | Informational; the tab matches on the code value. |
| `SLEEP_DX_CODES` | (built-in list) | Optional JSON array of `{"code": ..., "display": ...}` to override the diagnosis menu. |

## Structure

- `applications/sleep_screening_app.py` - the note tab (NoteApplication), gated on the reason for visit.
- `handlers/sleep_screening_api.py` - SimpleAPI serving the UI and the commit/stage endpoints.
- `handlers/scorer_handler.py` - writes the structured score after each questionnaire commits.
- `scoring/` - pure-function scorers for the three instruments.
- `questionnaires/` - the three bundled questionnaire definitions (install regardless of instance config).
- `templates/sleep_screening.html` - the in-app UI.
