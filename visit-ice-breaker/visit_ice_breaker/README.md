# Visit Ice Breaker

Displays a fun, age-appropriate ice breaker question when a new office visit note is created, helping clinicians start conversations with patients.

## Trigger

Responds to `NOTE_STATE_CHANGE_EVENT_CREATED`. Fires only when:
- The note state is `NEW`
- The note type is `Office visit`

## Behavior

1. Reads the patient's `birth_date` to determine their age group (Kids 0-12, Teens 13-17, Adults 18-64, Seniors 65+)
2. Selects a random question from an age-appropriate pool, excluding questions the patient has already seen
3. Originates an `InstructCommand` in the note with the question text
4. The clinician can record the patient's response in the command's comment field

## Persistence

Uses a `ShownQuestion` CustomModel (namespace: `metriport__visit_ice_breaker`) to track:
- Which question was shown for each note (idempotent on re-open)
- Which questions each patient has seen across all visits (no repeats)

When all questions for an age group are exhausted (12 per group), the pool resets.

## Configuration

No secrets or manual configuration required. The `namespace_read_write_access_key` is auto-generated on first install.
