# Carry Forward Plugin

A Canvas plugin that enables efficient clinical documentation by automatically carrying forward commands from previous encounters into new notes.

## Overview

The Carry Forward plugin adds action buttons to the note header that allow clinicians to quickly populate new notes with relevant information from previous encounters. This reduces documentation time and ensures continuity of care by intelligently carrying forward diagnoses, medications, orders, and other clinical data.

## Features

### Core Features

- **Carry Forward Last Note** - Automatically brings forward all relevant commands from the most recent note
- **Smart Transformations** - Intelligently transforms commands based on clinical workflow:
  - Diagnose → Assess (updates diagnosis to assessment)
  - Prescribe → Refill (converts new prescriptions to refills)
  - Goal → Update Goal (transforms new goals to goal updates)
  - And more...

### Supported Note Types

The carry forward button appears in:
- Office visit
- Telehealth
- Phone call
- Home visit

### Supported Commands

The plugin supports carrying forward the following command types:

#### Clinical Documentation
- History of Present Illness (HPI)
- Reason for Visit
- Review of Systems (ROS)
- Physical Exam
- Plan
- Assessment

#### Conditions & Diagnoses
- Diagnose (transforms to Assess)
- Assess
- Update Diagnosis (transforms to Assess)

#### Medications
- Prescribe (transforms to Refill)
- Refill
- Adjust Prescription (transforms to Refill)
- Change Medication (transforms to Refill)

#### Orders & Referrals
- Lab Order
- Imaging Order
- Refer
- Follow Up

#### Goals & Care Planning
- Goal (transforms to Update Goal)
- Update Goal

#### Other
- Vitals
- Perform
- Instruct
- Task
- Questionnaire

## How It Works

### Button Visibility

The "Carry Forward Last Note" button appears when:
1. The current note is one of the supported note types
2. The note body is empty (no commands have been added yet)
3. A previous note with commands exists for the patient

### Smart Carry Forward Logic

The plugin implements intelligent transformations to match clinical workflow:

#### Diagnose → Assess
When a previous note diagnosed a condition, the plugin carries it forward as an assessment rather than re-diagnosing it. This reflects the natural progression from initial diagnosis to ongoing management.

**Example:**
- Previous note: `Diagnose: Hypertension (I10)`
- Carried forward as: `Assess: Hypertension - stable, well controlled`

#### Medication Commands → Refill
Any medication-related command (prescribe, adjust prescription, change medication) is intelligently converted to a refill command, as clinicians typically want to continue existing medications rather than write new prescriptions.

**Example:**
- Previous note: `Prescribe: Lisinopril 10mg, #30, 90 day supply`
- Carried forward as: `Refill: Lisinopril 10mg, #30, 90 day supply`

#### Goal → Update Goal
New goals from previous encounters are carried forward as goal updates with progress tracking.

**Example:**
- Previous note: `Goal: Lose 10 pounds by end of year`
- Carried forward as: `Update Goal: Weight loss goal - in progress`

### Finding Previous Notes

The plugin searches for the most recent note that:
- Belongs to the same patient
- Is one of the supported note types
- Has a datetime of service before the current note
- Is in a valid state (signed, locked, etc.)
- Contains commands (non-empty body)


## Development

### Project Structure

```
carry-forward/
├── carry_forward/
│   ├── protocols/
│   │   └── carry_forward_action_button.py
│   └── CANVAS_MANIFEST.json
├── tests/
│   ├── conftest.py
│   └── protocols/
│       └── test_carry_forward_action_button.py
├── pyproject.toml
└── README.md
```

### Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run with verbose output
uv run pytest tests/ -v

# Run specific test class
uv run pytest tests/protocols/test_carry_forward_action_button.py::TestCarryForwardMethods -v

# Run with coverage (note: coverage reporting is limited due to extensive mocking)
uv run pytest tests/ --cov=carry_forward
```

### Test Coverage

The plugin has **65 comprehensive tests** organized into:

- **TestNoteBodyIsEmpty** - Helper method tests
- **TestFindPreviousNote** - Previous note lookup tests
- **TestVisible** - Button visibility logic tests
- **TestHandle** - Integration tests via handle() method
- **TestSmartCarryForward** - Smart transformation tests
- **TestQuestionnaireCommands** - Questionnaire-based command tests
- **TestCarryForwardMethods** - Direct unit tests for all `_carry_forward_*` methods

Coverage: **~95-98%** of functional code

### Adding New Command Support

To add support for a new command type:

1. **Create a carry forward handler method:**
```python
def _carry_forward_new_command(self, effect, data, command=None):
    """Carry forward new command data"""
    effect.some_field = data.get('some_field')
    # ... map other fields
    return effect
```

2. **Add to schema_map in handle() method:**
```python
schema_map = {
    # ...
    "newCommand": (NewCommand, self._carry_forward_new_command, False),
}
```

3. **Write tests:**
```python
def test_handle_new_command(self, mock_event, mock_note, mock_previous_note):
    """Test carrying forward a new command."""
    # Test integration through handle()

def test_carry_forward_new_command(self):
    """Test _carry_forward_new_command method directly."""
    # Test the method directly
```

## Usage

1. Open a new note for a patient
2. If the patient has a previous note with commands, the "Carry Forward Last Note" button will appear in the note header
3. Click the button to automatically populate the note with relevant information from the previous encounter
4. Review and modify the carried forward commands as needed
5. Complete your documentation as usual


## Technical Details

### Key Methods

- **`visible()`** - Determines button visibility based on note state
- **`handle()`** - Main handler that processes carry forward action
- **`note_body_is_empty()`** - Checks if note has any commands
- **`find_previous_note()`** - Locates the most recent applicable note
- **`_carry_forward_*()`** - Individual handlers for each command type


## Known Limitations

- Only carries forward from the most recent note 
- Not all commands are implemented to carry forward. (E.g if you stop a medication, that shouldn't carry forward). 
