# Automated PHQ-9 Followup

## Overview

This plugin automates the PHQ-2 to PHQ-9 depression screening escalation workflow. When a clinician commits a PHQ-2 questionnaire with a positive screen (score > 2), the plugin automatically originates a PHQ-9 questionnaire in the same note and pre-populates any overlapping questions so the clinician does not have to re-enter responses.

### Clinical Context

The PHQ-2 is a brief two-question depression screening tool. A score greater than 2 indicates a positive screen and warrants follow-up with the full PHQ-9, a nine-question diagnostic assessment. This plugin removes the manual step of opening and filling out the PHQ-9 after a positive PHQ-2, keeping the clinician in their documentation flow.

## How It Works

1. A clinician commits a questionnaire command in a note.
2. The plugin checks whether the committed questionnaire is a PHQ-2 (LOINC `58120-7`).
3. If it is not a PHQ-2, the plugin exits with no action.
4. The plugin scores the PHQ-2 by summing the numerical values of all non-text responses.
5. If the score is 2 or less (negative screen), the plugin exits with no action.
6. If the score is greater than 2 (positive screen), the plugin:
   - Creates a new PHQ-9 (LOINC `44249-1`) questionnaire command in the same note
   - Matches questions between the PHQ-2 and PHQ-9 by LOINC code
   - Pre-fills matching PHQ-9 responses with the values already recorded in the PHQ-2
   - Originates and edits the new command so it appears in the note with responses already populated

Both the original PHQ-2 and the new PHQ-9 remain in the note, preserving a complete audit trail.

## Event and Effects

| Event | Effects |
|---|---|
| `QUESTIONNAIRE_COMMAND__POST_COMMIT` | `QuestionnaireCommand.originate()` + `QuestionnaireCommand.edit()` |

## Questionnaires Required

Both questionnaires must exist in the Canvas instance's questionnaire catalog with the correct LOINC codes and must be enabled for charting origination.

| Questionnaire | Code System | Code | Purpose |
|---|---|---|---|
| PHQ-2 | LOINC | `58120-7` | Initial two-question depression screen |
| PHQ-9 | LOINC | `44249-1` | Full nine-question depression diagnostic assessment |

## Configuration

No secrets, environment variables, or custom settings are required. The plugin works out of the box once installed.

## Installation

```bash
uv run canvas install phq9_followup --host <your-host>
```

## Limitations

- **Incomplete PHQ-2**: If not all non-text questions on the PHQ-2 are answered, the score returns `None` and the plugin will still originate a PHQ-9 (it treats an incomplete score the same as an abnormal score).
- **No automatic removal**: If the PHQ-2 command is later entered in error, the originated PHQ-9 is not automatically removed. Manual cleanup is required.
