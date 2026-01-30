# Command Validation

Validates commands before commit to ensure data completeness and quality.

## Event Reference

This plugin responds to `QUESTIONNAIRE_COMMAND__PRE_COMMIT`, which fires before a questionnaire command is committed. Returning a `CommandValidationErrorEffect` blocks the commit and displays the error to the user.

## Handlers

### RequireAllQuestionsAnsweredHandler

Prevents committing a questionnaire unless all questions have been answered.

**Validation Rule:** When a user attempts to commit a questionnaire command, this handler checks that every question in the questionnaire has at least one response. If any questions are unanswered, the commit is blocked.

**Error Messages:**

When 3 or fewer questions are unanswered, the specific questions are listed:
```
Cannot commit questionnaire: 2 question(s) unanswered. Please answer: Height, Blood Pressure
```

When more than 3 questions are unanswered, a summary is shown:
```
Cannot commit questionnaire: 8 of 10 questions unanswered. Please answer all questions before committing.
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
│   └── questionnaire_validation.py   # RequireAllQuestionsAnsweredHandler
├── CANVAS_MANIFEST.json
├── README.md
└── __init__.py
```
