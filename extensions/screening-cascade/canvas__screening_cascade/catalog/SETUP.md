## Before you start

- The screener and follow-up questionnaires the practice uses, and the codes they carry in Canvas.
- Agree the positive threshold with the practice's clinical lead.
- For a clinician preference (for example HAM-D instead of MADRS), the staff ids of the clinicians who prefer it.
- A test patient and a note.

## Settings

- `SCREENING_CASCADE_ENABLED` (default `false`): `true` turns the plugin on.
- `SCREENING_CASCADE_RULES` (optional, default blank): the rules, as JSON. Left blank, the PHQ-2 to PHQ-9 and GAD-2 to GAD-7 rules apply. Set, it replaces them. See the README for the fields of a rule and a PHQ-9 to MADRS example.

## Steps

1. Install the plugin with `SCREENING_CASCADE_ENABLED` set to `true`.
2. On a test patient's note, add PHQ-2 and answer so the total is 3 or more, then commit it.
3. Check PHQ-9 appears on the same note.
4. Repeat with a total under 3 and check nothing is added.
5. Commit a second positive PHQ-2 on a new note within the waiting period and check PHQ-9 is not added again.
