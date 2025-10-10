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

Triggers when vitals commands are committed. Retrieves systolic and diastolic blood pressure readings and adds billing codes based on the measurements.

**Event**: `VITALS_COMMAND__POST_COMMIT`

The handler checks for existing billing line items before adding new ones. If a billing code already exists on the note, it will not be added again, preventing duplicates.

When BP is not documented, the handler checks vitals command data (the `note` field in command.data) for documented reasons. If text matching patterns like "bp not documented reason", "blood pressure not taken because", "patient refused", or similar phrases is found, code G8951 is used instead of G8950.

#### BloodPressureNoteStateHandler

Triggers when notes are locked or charges are pushed. Analyzes clinical documentation using AI to determine if blood pressure treatment plans are documented for patients with uncontrolled hypertension.

**Event**: `NOTE_STATE_CHANGE_EVENT_UPDATED` (only processes when state is 'LKD' or 'PSH')

The handler uses OpenAI's GPT-4 model to analyze:
- All commands documented in the note
- Active medications for the patient

For notes with uncontrolled BP (>= 140/90 mm Hg), the AI determines whether a treatment plan is documented and adds the appropriate treatment code:
- **G8753**: Treatment plan is documented (new medications, lifestyle modifications, follow-up plans, etc.)
- **G8754**: No treatment plan documented, no reason given
- **G8755**: No treatment plan documented, but reason is documented (e.g., "patient declined", "awaiting specialist")

The handler checks for existing billing line items before adding new ones to prevent duplicates.

## Configuration

### Required Secrets

The plugin requires the following secret to be configured in Canvas:

- **OPENAI_API_KEY**: Your OpenAI API key for GPT-4 access. This is used by the note state handler to analyze treatment plan documentation.

The secret is declared in the `CANVAS_MANIFEST.json` file:

```json
"secrets": [
    "OPENAI_API_KEY"
]
```

To configure the secret value, add it to your Canvas instance's secrets configuration. The plugin will access it via `self.secrets.get('OPENAI_API_KEY')` in the note state handler.

## Limitations

### Automatic Removal
Billing line items added by this plugin will not be automatically removed if the vitals command is entered in error. Manual removal of billing codes is required if incorrect vitals data is corrected or deleted.

### Diagnosis Pointers
The billing codes added by this plugin do not include diagnosis pointers. Diagnosis pointer assignment could be implemented by analyzing documented diagnoses in the note.

### Treatment Plan Analysis
The treatment plan analysis (G8753-G8755) relies on AI interpretation of clinical documentation. The accuracy depends on:
- Clear documentation of treatment plans in commands and medications
- Proper recording of clinical decisions and rationale
- The quality of the LLM's analysis

If the OpenAI API key is not configured, the handler will default to adding G8754 (no treatment plan, reason not given) for uncontrolled BP.

## Running Tests

```bash
# Run tests
uv run pytest tests/

# Run tests with coverage report
uv run pytest tests/ --cov=.
```

## Installation

To install this plugin to a Canvas instance:

```bash
uv run canvas install bp_cpt2 --host plugin-testing --secret OPENAI_API_KEY="Your OpenAI API Key"
```

**Important**: The OpenAI API key **must** be associated with a U.S. region project. API keys from other regions will not work with this plugin. You can verify your project's region in your OpenAI account settings.

## Simple Example Note with Claim Coding
<img width="600" height="714" alt="image" src="https://github.com/user-attachments/assets/4e072ef8-5d80-41f2-8b7d-91c5cf3ab822" />
