# Installing Screening Follow-up Cascade (canvas__screening_cascade)

The plugin runs only when a questionnaire is committed. It adds a questionnaire command to the same note and, if a rule asks for it, records the screener's score. It has no UI, no API routes and makes no outside calls.

## Settings to collect

- `SCREENING_CASCADE_ENABLED`: `false` until step 3, then `true`.
- `SCREENING_CASCADE_RULES`: blank for the built-in PHQ-2 to PHQ-9 and GAD-2 to GAD-7 rules. Otherwise a JSON list of rules built with the practice's clinical lead; it replaces the built-in rules, so include them if the practice still wants them. Invalid JSON makes the plugin log an error and do nothing.

## Steps

1. Ask the practice which screeners and follow-ups it uses. In Canvas, read each questionnaire's code system and code. The follow-up must be active and allowed to originate in charting.
2. Install with `SCREENING_CASCADE_ENABLED` set to `false` and `SCREENING_CASCADE_RULES` blank or set to the agreed rules. For a clinician preference, put the staff ids under `follow_up_by_staff`; the choice follows the note's provider.
3. Set `SCREENING_CASCADE_ENABLED` to `true`.
4. Check: on a test patient's note, commit a PHQ-2 with a total of 3 or more. PHQ-9 appears on the same note.
5. Commit a PHQ-2 with a total under 3 on another test note. Nothing is added.
6. For each custom rule, repeat steps 4 and 5 with that rule's screener and threshold.
7. Never test on a real patient's chart.
