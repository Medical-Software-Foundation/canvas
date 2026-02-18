# Delete Staged Commands Button Plugin

## Overview

The Delete Staged Commands Button plugin adds a convenient action button to the Canvas note header that allows users to quickly remove all staged (uncommitted) commands from the current note with a single click.

This plugin is useful when:
- A clinician wants to start fresh with their note documentation
- Staged commands need to be cleared after all needed commands are committed
- Multiple staged commands need to be removed at once instead of individually

## Features

- **One-Click Deletion**: Removes all staged commands in the current note with a single button click
- **Comprehensive Command Support**: Handles 38+ different command types including diagnoses, prescriptions, orders, assessments, and more
- **Safe Operation**: Only deletes commands in the "staged" state - committed commands are never affected
- **Visual Feedback**: Button appears in the note header for easy access
- **Error Handling**: Logs warnings for any unsupported command types

## Usage

### For Clinicians

1. Open a note in Canvas
2. Look for the **"Delete All Staged Commands"** button in the note header
3. Click the button to remove all staged commands from the current note
4. The button is always visible and ready to use

**Note**: This action only affects staged (uncommitted) commands. Once a note is committed, those commands cannot be deleted using this button.

### Button Behavior

- **Location**: Note header (top of the note interface)
- **Title**: "Delete All Staged Commands"
- **Action**: Deletes all commands in "staged" state for the current note
- **Visibility**: Always visible when viewing a note

## Supported Command Types

The plugin supports deletion of the following 38 command types:

| Command Type | Schema Key | Description |
|-------------|------------|-------------|
| Adjust Prescription | `adjustPrescription` | Medication adjustments |
| Allergy | `allergy` | Allergy documentation |
| Assess | `assess` | Clinical assessments |
| Change Medication | `changeMedication` | Medication changes |
| Close Goal | `closeGoal` | Goal closure |
| Diagnose | `diagnose` | Diagnosis documentation |
| Physical Exam | `exam` | Physical examination findings |
| Family History | `familyHistory` | Family medical history |
| Follow Up | `followUp` | Follow-up instructions |
| Goal | `goal` | Patient goals |
| History of Present Illness | `hpi` | HPI documentation |
| Imaging Order | `imagingOrder` | Imaging test orders |
| Imaging Review | `imagingReview` | Imaging result reviews |
| Immunization Statement | `immunizationStatement` | Immunization records |
| Instruct | `instruct` | Patient instructions |
| Lab Order | `labOrder` | Laboratory test orders |
| Lab Review | `labReview` | Lab result reviews |
| Medical History | `medicalHistory` | Past medical history |
| Medication Statement | `medicationStatement` | Medication lists |
| Perform | `perform` | Procedures performed |
| Plan | `plan` | Care plan documentation |
| Prescribe | `prescribe` | New prescriptions |
| Questionnaire | `questionnaire` | Questionnaire responses |
| Reason for Visit | `reasonForVisit` | Visit reason documentation |
| Refer | `refer` | Referral orders |
| Referral Review | `referralReview` | Referral reviews |
| Refill | `refill` | Prescription refills |
| Remove Allergy | `removeAllergy` | Allergy removal |
| Resolve Condition | `resolveCondition` | Condition resolution |
| Review of Systems | `ros` | ROS documentation |
| Stop Medication | `stopMedication` | Medication discontinuation |
| Structured Assessment | `structuredAssessment` | Structured assessments |
| Past Surgical History | `surgicalHistory` | Surgical history |
| Task | `task` | Clinical tasks |
| Uncategorized Document Review | `uncategorizedDocumentReview` | Document reviews |
| Update Diagnosis | `updateDiagnosis` | Diagnosis updates |
| Update Goal | `updateGoal` | Goal updates |
| Vitals | `vitals` | Vital signs |

## Technical Details

### Architecture

The plugin implements the Canvas SDK `ActionButton` handler pattern:

```python
class DeleteCommandActionButton(ActionButton):
    BUTTON_TITLE = "Delete All Staged Commands"
    BUTTON_KEY = "DELETE_ALL_STAGED_COMMANDS"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER
```

### How It Works

1. **Button Click**: When the button is clicked, the `handle()` method is triggered
2. **Note Lookup**: Retrieves the current note using the note_id from the event context
3. **Command Query**: Finds all commands associated with the note where `state="staged"`
4. **Schema Mapping**: Maps each command's `schema_key` to its corresponding Canvas SDK command class
5. **Effect Creation**: Creates a delete effect for each staged command using `CommandClass(command_uuid=str(command.id)).delete()`
6. **Execution**: Returns the list of delete effects to be executed by Canvas

### Key Components

- **Note Context**: Uses `self.event.context['note_id']` to identify the current note
- **Command Filtering**: Queries `Command.objects.filter(note=note, state="staged")`
- **Schema Map**: Dictionary mapping schema keys to command classes using `CommandClass.Meta.key`
- **Error Handling**: Logs warnings for unsupported command types

## Development

### Running Tests

The plugin includes comprehensive test coverage with 11 test cases:

```bash
# Run all tests
uv run pytest tests/ -v

# Run with coverage report
uv run pytest tests/ --cov=delete_staged_commands_button --cov-report=term-missing
```

### Test Coverage

- **Visibility Tests** (1 test): Verifies button visibility logic
- **Handle Method Tests** (7 tests):
  - Single command deletion
  - Multiple command deletion
  - Empty command list handling
  - All 38 command types support
  - Unsupported command type handling
  - Specific command type deletion
  - Staged-only filtering
- **Configuration Tests** (3 tests):
  - Button title
  - Button key
  - Button location

**Total**: 11 tests, all passing

### Project Structure

```
delete-staged-commands-button/
├── pyproject.toml                    # Project configuration
├── mypy.ini                          # Type checking configuration
├── tests/
│   ├── conftest.py                   # Test fixtures and mocks
│   └── protocols/
│       └── test_delete_command_action_button.py
└── delete_staged_commands_button/    # Main plugin package
    ├── CANVAS_MANIFEST.json          # Canvas plugin manifest
    ├── README.md                     # This file
    └── protocols/
        └── delete_command_action_button.py
```

### Adding New Command Types

If Canvas adds new command types in the future:

1. Import the new command class
2. Add to the `schema_map` dictionary in `delete_command_action_button.py`
3. Add corresponding mock in `tests/conftest.py`
4. Add test case to verify support

Example:
```python
# In delete_command_action_button.py
from canvas_sdk.commands import NewCommand

schema_map = {
    # ... existing mappings
    NewCommand.Meta.key: NewCommand,
}
```