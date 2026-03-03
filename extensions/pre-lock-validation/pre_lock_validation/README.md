# Pre-Lock Validation

Validates pre-lock conditions before allowing a note to be locked. This plugin uses the `NOTE_STATE_CHANGE_EVENT_PRE_CREATE` event to intercept note state transitions and enforce business rules.

## Event Reference

This plugin responds to `NOTE_STATE_CHANGE_EVENT_PRE_CREATE`, which fires before a note state change is created. Returning an `EventValidationError` effect blocks the state change and displays the error to the user.

## Handlers

### RequireVitalsToLockHandler

Prevents locking a note unless it contains committed vitals.

**Validation Rule:** When a user attempts to lock a note (state = `LKD`), this handler checks for the presence of a committed command with `schema_key="vitals"`. If no committed vitals exist, the lock is blocked.

**Error Message:**
```
Cannot lock note: Vitals must be recorded and committed before locking.
```

### NoStagedCommandsToLockHandler

Prevents locking a note if there are any staged (uncommitted) commands.

**Validation Rule:** When a user attempts to lock a note, this handler checks for any commands in the `staged` state. If staged commands exist, the lock is blocked and the user is informed of how many commands need attention and what types they are.

**Exclusions:** `reasonForVisit` commands are excluded from this validation.

**Error Message:**
```
Cannot lock note: 3 staged command(s) must be committed or removed before locking. Staged command types: diagnose, prescribe
```

## Development

### Running Tests

```bash
uv run pytest
```

### Test Coverage

```bash
uv run pytest --cov=pre_lock_validation --cov-report=term-missing
```

## File Structure

```
pre_lock_validation/
├── handlers/
│   ├── __init__.py
│   ├── require_vitals.py         # RequireVitalsToLockHandler
│   └── no_staged_commands.py     # NoStagedCommandsToLockHandler
├── CANVAS_MANIFEST.json
├── README.md
└── __init__.py
```
