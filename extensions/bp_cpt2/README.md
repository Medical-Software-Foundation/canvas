# Blood Pressure CPT Billing Plugin

## Overview

This plugin automatically adds appropriate CPT and HCPCS billing codes based on blood pressure measurements recorded in Canvas. It responds to two types of events: when vitals are committed and when notes are locked.

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

### Event Handlers

#### BloodPressureVitalsHandler

Triggers when vitals commands are committed. Retrieves systolic and diastolic blood pressure readings and adds billing codes based on the measurements.

**Event**: `VITALS_COMMAND__POST_COMMIT`

The handler checks for existing billing line items before adding new ones. If a billing code already exists on the note, it will not be added again, preventing duplicates.

When BP is not documented, the handler checks vitals command data (the `note` field in command.data) for documented reasons. If text matching patterns like "bp not documented reason", "blood pressure not taken because", "patient refused", or similar phrases is found, code G8951 is used instead of G8950.

#### BloodPressureNoteStateHandler

This handler is registered for note state change events but is currently not implemented. It is reserved for future implementation of treatment plan codes (G8753-G8755) which require analyzing note content for treatment plan documentation.

**Event**: `NOTE_STATE_CHANGE_EVENT_CREATED` (only processes when state is 'LKD')

All BP measurement codes (3074F-3080F, G8783, G8784, G8950, G8951, G8752) are currently handled by the BloodPressureVitalsHandler when vitals are committed.

## Limitations

### Automatic Removal
Billing line items added by this plugin will not be automatically removed if the vitals command is entered in error. Manual removal of billing codes is required if incorrect vitals data is corrected or deleted.

### Diagnosis Pointers
The billing codes added by this plugin do not include diagnosis pointers. Diagnosis pointer assignment could be implemented in the note state handler by analyzing documented diagnoses in the note.

### Codes Not Handled
The following CPT/HCPCS codes are not returned by this plugin:

- **G8753** (Most recent BP >= 140/90 and treatment plan documented): This plugin does not analyze whether a treatment plan has been documented in the note. It only evaluates BP values and control status.

- **G8754** (Most recent BP >= 140/90 and no treatment plan, reason not given): This plugin does not track treatment plan documentation or reasons for its absence.

- **G8755** (Most recent BP >= 140/90 and no treatment plan, documented reason): This plugin does not track treatment plan documentation or reasons for its absence.

To support these codes, the plugin would need to parse note content for treatment plans and documented reasons, which is outside the current scope.

## Running Tests

```bash
# Run tests
uv run pytest tests/

# Run tests with coverage report
uv run pytest tests/ --cov=.
```
