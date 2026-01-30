# Command Validation

Validates commands before commit to ensure data completeness and quality.

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
