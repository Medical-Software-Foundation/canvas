# Blood Pressure CPT-II and HCPCS Claim Coding Agent

## Overview

This AI agent automatically adds appropriate CPT and HCPCS billing codes based on blood pressure measurements recorded in Canvas. It responds to two types of events: when vitals are committed and when notes are locked.

## Functionality

### Billing Codes

The plugin determines which codes to add based on blood pressure values:

#### Systolic Measurement Codes
- 3074F: < 130 mm Hg
- 3075F: 130-139 mm Hg
- 3077F: >= 140 mm Hg

#### Diastolic Measurement Codes
- 3078F: < 80 mm Hg
- 3079F: 80-89 mm Hg
- 3080F: >= 90 mm Hg

#### Control Status Codes
- G8783: BP documented and controlled (< 140/90 mm Hg)
- G8784: BP documented but not controlled (>= 140/90 mm Hg)
- G8950: BP not documented, reason not given
- G8951: BP not documented, documented reason
- G8752: Most recent BP < 140/90 mm Hg

#### Treatment Plan Codes (Uncontrolled BP)
- G8753: Most recent BP >= 140/90 and treatment plan documented
- G8754: Most recent BP >= 140/90 and no treatment plan, reason not given
- G8755: Most recent BP >= 140/90 and no treatment plan, documented reason

### Event Handlers

#### BloodPressureVitalsHandler

Triggers when vitals commands are committed. Retrieves systolic and diastolic blood pressure readings from up to the 3 most recent observations for the note and calculates the minimum values to use for billing codes.

**Event**: `VITALS_COMMAND__POST_COMMIT`

**Key Features**:
- **Minimum BP Calculation**: Uses the minimum systolic and minimum diastolic from up to 3 most recent BP observations per note
- **Smart Updates**: Updates existing billing codes when BP measurements change (e.g., if BP improves from 145/95 to 130/85, updates codes accordingly)
- **Hypertension Assessment Filtering**: Uses AI to identify only hypertension-related assessments (via ICD-10 codes) and links them to billing line items
- **Documented Reason Detection**: Checks vitals command data for documented reasons when BP is not recorded (uses G8951 instead of G8950)

When BP is not documented, the handler checks vitals command data (the `note` field in command.data) for documented reasons. If text matching patterns like "bp not documented reason", "blood pressure not taken because", "patient refused", or similar phrases is found, code G8951 is used instead of G8950.

The handler uses an OpenAI LLM to analyze assessment condition codings (filtered to ICD-10 codes only) and determine which assessments are hypertension-related. Only these filtered assessments are included in the `assessment_ids` field of billing line items.

#### BloodPressureNoteStateHandler

Triggers when notes are locked or charges are pushed. Analyzes clinical documentation using AI to determine if blood pressure treatment plans are documented for patients with uncontrolled hypertension.

**Event**: `NOTE_STATE_CHANGE_EVENT_UPDATED` (only processes when state is 'LKD' or 'PSH')

**Note**: This handler can be enabled or disabled via the `INCLUDE_TREATMENT_PLAN_CODES` secret configuration (see Configuration section below).

The handler uses AI to analyze:
- All commands documented in the note
- Active medications for the patient

For notes with uncontrolled BP (>= 140/90 mm Hg), the AI determines whether a treatment plan is documented and adds the appropriate treatment code:
- **G8753**: Treatment plan is documented (new medications, lifestyle modifications, follow-up plans, etc.)
- **G8754**: No treatment plan documented, no reason given
- **G8755**: No treatment plan documented, but reason is documented (e.g., "patient declined", "awaiting specialist")

The handler checks for existing billing line items before adding new ones to prevent duplicates.

## Configuration

### Secrets

The plugin uses the following secrets configured in Canvas:

#### OPENAI_API_KEY (Required)
Your OpenAI API key for LLM access. This is used by both handlers:
- **BloodPressureVitalsHandler**: To identify hypertension-related assessments
- **BloodPressureNoteStateHandler**: To analyze treatment plan documentation

**Important**: The OpenAI API key **must** be associated with a U.S. region project. API keys from other regions will not work with this plugin.

#### INCLUDE_TREATMENT_PLAN_CODES (Optional)
Controls whether the BloodPressureNoteStateHandler runs and adds treatment plan codes (G8753-G8755).

**Accepted values**:
- **Truthy** (enable treatment codes): `true`, `True`, `y`, `yes`, `1`
- **Falsey** (disable treatment codes): `false`, `False`, `f`, `n`, `no`, `0`, or empty string

If not configured or set to a falsey value, the note state handler will return immediately without processing treatment plan codes. The vitals handler will continue to function normally.

## Limitations and Caveats

### Automatic Removal Upon Enter-in-error Event
Billing line items added by this plugin will not be automatically removed when the a vitals command is entered in error. Manual removal of billing codes is required if incorrect vitals data is corrected or deleted.

### Diagnosis Pointers (Hypertension-Related Only)
The vitals handler uses AI to identify hypertension-related assessments and links them to billing codes. The handler:
- Filters assessment condition codings to ICD-10 codes only
- Uses an Open AI LLM to analyze which assessments are clearly hypertension-related
- Only includes hypertension-related assessments in billing line items

Assessments for conditions that are merely risk factors (like diabetes or obesity) or general complications are excluded from the billing codes.

### Treatment Plan Analysis
The treatment plan analysis (G8753-G8755) relies on AI interpretation of clinical documentation. The accuracy depends on:
- Clear documentation of treatment plans in commands and medications
- Proper recording of clinical decisions and rationale
- The quality of the LLM's analysis

If the OpenAI API key is not configured, the vitals handler will skip hypertension assessment filtering and use all assessments. The note state handler will default to adding G8754 (no treatment plan, reason not given) for uncontrolled BP.

## Running Tests

```bash
# Run tests
uv run pytest tests/

# Run tests with coverage report
uv run pytest tests/ --cov=.

Name                                        Stmts   Miss  Cover
---------------------------------------------------------------
bp_cpt2/handlers/__init__.py                    0      0   100%
bp_cpt2/handlers/bp_note_state_handler.py      93      0   100%
bp_cpt2/handlers/bp_vitals_handler.py         141      0   100%
bp_cpt2/llm_openai.py                          64      0   100%
bp_cpt2/utils.py                               34      0   100%
---------------------------------------------------------------
TOTAL                                         332      0   100%
```

## Installation

To install this plugin to a Canvas instance:

```bash
# Install with both secrets (treatment plan codes enabled)
uv run canvas install bp_cpt2 --host <your-host> \
  --secret OPENAI_API_KEY="<Your OpenAI API Key>" \
  --secret INCLUDE_TREATMENT_PLAN_CODES="true"

# Install with only vitals codes (treatment plan codes disabled)
uv run canvas install bp_cpt2 --host <your-host> \
  --secret OPENAI_API_KEY="<Your OpenAI API Key>" \
  --secret INCLUDE_TREATMENT_PLAN_CODES="false"
```

**Important**: The OpenAI API key **must** be associated with a U.S. region project. API keys from other regions will not work with this plugin. You can verify your project's region in your OpenAI account settings.

## Example Note with Claim Coding
![Blood Pressure CPT-II claim coding example](https://images.prismic.io/canvas-website/aRJesLpReVYa4Ubn_499768700-4e072ef8-5d80-41f2-8b7d-91c5cf3ab822.png?auto=format,compress)
