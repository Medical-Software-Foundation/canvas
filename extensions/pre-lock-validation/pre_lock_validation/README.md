# Pre-Lock Validation

Validates pre-lock conditions before allowing a note to be locked. This plugin uses the `NOTE_STATE_CHANGE_EVENT_PRE_CREATE` event to intercept note state transitions and enforce business rules.

## What it does

When a user tries to lock a note, this plugin checks the note before the lock goes through. It blocks the lock and shows an error if the note has no committed vitals, or if any commands are still staged (not yet committed). The user has to fix what the message points to before they can lock.

## Problem it solves

Notes get locked with vitals missing or with half-finished commands left in a staged state, and the gaps are only caught later during chart review or coding. Catching those gaps after the fact means reopening the note and chasing down the clinician. This plugin stops the lock at the point of the mistake so the note cannot close with those gaps in it.

## Who it's for

Clinicians and prescribers who lock encounter notes, and the practices that need vitals recorded and all commands committed on every locked note.

## How to install

```
canvas install pre_lock_validation
```

## Configuration options

No configuration required.

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
