# Blood Pressure CPT-II and HCPCS Claim Coding Agent

## Overview

This AI agent automatically adds the CPT II and HCPCS quality codes for blood pressure to a note when vitals are recorded in Canvas, then links them to the note's hypertension diagnoses when the note is locked. It responds to two types of events: when vitals are committed and when notes are locked.

## Problem it solves

CPT II and HCPCS quality codes for blood pressure are tied to specific systolic and diastolic ranges, and each payer program uses its own set, so picking the right codes by hand is error-prone and often skipped. This plugin replaces that manual lookup and entry, reading the recorded BP and adding or updating the matching codes.

## Who it's for

Prescribers managing hypertension and the billing and coding staff responsible for CPT II and HCPCS quality reporting, especially practices tracking blood pressure control measures.

## Functionality

### Billing Codes

The codes follow the 2026 specifications for two blood pressure control measures:
- **HEDIS Controlling High Blood Pressure (CBP)**, measurement year 2026, which uses CPT II codes
- **MIPS Quality ID #236, Controlling High Blood Pressure** (Medicare Part B claims, 2026), which uses HCPCS codes

For a note with a blood pressure, the plugin adds one code from each group below: four codes in total.

#### HEDIS CPT II Codes
- 3074F: Most recent systolic BP < 130 mm Hg
- 3075F: Most recent systolic BP 130-139 mm Hg
- 3077F: Most recent systolic BP >= 140 mm Hg
- 3078F: Most recent diastolic BP < 80 mm Hg
- 3079F: Most recent diastolic BP 80-89 mm Hg
- 3080F: Most recent diastolic BP >= 90 mm Hg

#### MIPS Measure 236 HCPCS Codes
- G8752: Most recent systolic BP < 140 mm Hg
- G8753: Most recent systolic BP >= 140 mm Hg
- G8754: Most recent diastolic BP < 90 mm Hg
- G8755: Most recent diastolic BP >= 90 mm Hg

If the note has no complete blood pressure reading, the plugin adds no codes. It doesn't add G8756 (no BP documented, reason not given): measure 236 scores the patient's most recent code, so adding G8756 at a visit without a BP would replace a reading from an earlier visit that year.

### Event Handlers

#### BloodPressureVitalsHandler

Triggers when vitals commands are committed. Retrieves systolic and diastolic blood pressure readings from up to the 3 most recent observations for the note and calculates the minimum values to use for billing codes.

**Event**: `VITALS_COMMAND__POST_COMMIT`

**Key Features**:
- **Minimum BP Calculation**: Uses the lowest systolic and lowest diastolic from up to 3 most recent BP observations per note, which is how both measures treat several readings on the same day
- **Smart Updates**: Updates existing billing codes when BP measurements change (e.g., if BP improves from 145/95 to 130/85, 3077F becomes 3075F, 3080F becomes 3079F, G8753 becomes G8752 and G8755 becomes G8754)

#### BloodPressureNoteStateHandler

Triggers when a billable note is locked. Uses an OpenAI LLM to find the note's hypertension-related assessments and links them to the BP billing codes as diagnosis pointers.

**Event**: `NOTE_STATE_CHANGE_EVENT_UPDATED` (only processes when state is 'LKD')

#### BloodPressureNoteButtonHandler

A "BP CPT-II" button in the note header that runs the same diagnosis linking before the note is locked. It appears only when `SHOW_BUTTON_FOR_MANUAL_TRIGGER` is enabled.

## Configuration

### Secrets

The plugin uses the following secrets configured in Canvas:

#### OPENAI_API_KEY (Required)
Your OpenAI API key for LLM access. It's used to identify the hypertension-related assessments to link to the BP billing codes. Without it, the codes are still added but no diagnoses are linked.

**Important**: The OpenAI API key **must** be associated with a U.S. region project. API keys from other regions will not work with this plugin.

#### SHOW_BUTTON_FOR_MANUAL_TRIGGER (Optional)
Shows the "BP CPT-II" note header button while the note can be edited.

**Accepted values**:
- **Truthy** (show the button): `true`, `True`, `y`, `yes`, `1`
- **Falsey** (hide the button): `false`, `False`, `f`, `n`, `no`, `0`, or empty string

## Limitations and Caveats

### Automatic Removal Upon Enter-in-error Event
Billing line items added by this plugin will not be automatically removed when the a vitals command is entered in error. Manual removal of billing codes is required if incorrect vitals data is corrected or deleted.

### Measure Eligibility
The plugin codes every note with a blood pressure. It doesn't check who is eligible for measure 236 (patients 18-85 with essential hypertension and a qualifying visit), or the readings the measure excludes, such as those taken during an inpatient stay or ED visit. Codes on claims for patients outside a measure aren't counted toward it.

### Not Supported: MIPS Measure 317
Codes for MIPS Quality ID #317 (Screening for High Blood Pressure and Follow-Up Documented), such as G8783, G8950 and G8952, are not added. That measure excludes patients with a hypertension diagnosis and telehealth visits, uses its own BP thresholds, and requires follow-up documentation specific to each reading category.

### Diagnosis Pointers (Hypertension-Related Only)
The note state handler uses AI to identify hypertension-related assessments and links them to billing codes. The handler:
- Filters assessment condition codings to ICD-10 codes only
- Uses an Open AI LLM to analyze which assessments are clearly hypertension-related
- Only includes hypertension-related assessments in billing line items

Assessments for conditions that are merely risk factors (like diabetes or obesity) or general complications are excluded from the billing codes.

## Running Tests

```bash
# Run tests
uv run pytest tests/

# Run tests with coverage report
uv run pytest tests/ --cov=.

Name                                         Stmts   Miss  Cover
----------------------------------------------------------------
bp_cpt2/bp_claim_coder.py                      125      2    98%
bp_cpt2/handlers/__init__.py                     0      0   100%
bp_cpt2/handlers/bp_note_button_handler.py      34      0   100%
bp_cpt2/handlers/bp_note_state_handler.py       26      0   100%
bp_cpt2/handlers/bp_vitals_handler.py           72      0   100%
bp_cpt2/llm_openai.py                           64      0   100%
bp_cpt2/utils.py                                 4      0   100%
----------------------------------------------------------------
TOTAL                                          325      2    99%
```

## Installation

To install this plugin to a Canvas instance:

```bash
uv run canvas install bp_cpt2 --host <your-host> \
  --secret OPENAI_API_KEY="<Your OpenAI API Key>"

# Also show the "BP CPT-II" note header button
uv run canvas install bp_cpt2 --host <your-host> \
  --secret OPENAI_API_KEY="<Your OpenAI API Key>" \
  --secret SHOW_BUTTON_FOR_MANUAL_TRIGGER="true"
```

**Important**: The OpenAI API key **must** be associated with a U.S. region project. API keys from other regions will not work with this plugin. You can verify your project's region in your OpenAI account settings.

## Watch the Agent in Action
[![Watch the video](https://img.youtube.com/vi/bmPeq6rq1go/0.jpg)](https://www.youtube.com/watch?v=bmPeq6rq1go)
