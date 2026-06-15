# Command Validation

Validates commands before commit to ensure data completeness and quality.

## What it does

This plugin checks certain Canvas commands at commit time and blocks the commit if required data is missing. It will not let a questionnaire be committed while any question is still unanswered, and it will not let a prescription, refill, or prescription adjustment be committed without a days-supply value greater than zero. When a check fails, the staff member sees a clear message explaining what to fix.

## Problem it solves

Incomplete questionnaires and prescriptions with a missing days supply slip through and cause downstream rework: pharmacies reject scripts, reporting gaps appear, and someone has to chase the chart back open to fix it after the fact. This plugin catches the gap at the moment of commit instead of relying on staff to remember every required field or on a later manual audit.

## Who it's for

Prescribers and clinical staff who commit prescriptions, refills, and prescription adjustments, plus anyone who administers questionnaires during a visit. Practice administrators who want consistent, complete documentation also benefit.

## How to install

```
canvas install command_validation
```

## Configuration options

No configuration required.

## Handlers

### RequireAllQuestionsAnsweredHandler

Prevents committing a questionnaire unless all questions have been answered.

**Event:** `QUESTIONNAIRE_COMMAND__POST_VALIDATION`

**Validation Rule:** Checks that every question in the questionnaire has a response based on question type:
- **SING** (Single choice): Must have a selected option (integer pk)
- **MULT** (Multiple choice): At least one option must be selected
- **TXT** (Text): Must be a non-empty string

**Error Message:**
```
Cannot commit questionnaire: 2/3 questions unanswered.
```

### RequireDaysSupplyHandler

Prevents committing prescription commands without a valid days_supply.

**Events:**
- `PRESCRIBE_COMMAND__POST_VALIDATION`
- `REFILL_COMMAND__POST_VALIDATION`
- `ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION`

**Validation Rule:** The `days_supply` field must not be `None` or `0`.

**Error Message:**
```
Days supply is required and must be greater than 0.
```

## Development

### Running Tests

```bash
uv run pytest
```

### Test Coverage

```bash
uv run pytest --cov=command_validation --cov-report=term-missing
```

## File Structure

```
command_validation/
├── handlers/
│   ├── __init__.py
│   ├── questionnaire_validation.py   # RequireAllQuestionsAnsweredHandler
│   └── prescription_validation.py    # RequireDaysSupplyHandler
├── CANVAS_MANIFEST.json
├── README.md
└── __init__.py
```
