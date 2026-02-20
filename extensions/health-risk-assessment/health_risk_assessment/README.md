# Health Risk Assessment Plugin

A Canvas plugin for Medicare Annual Wellness Visit health risk assessments. Adds an ActionButton to the note header that launches an interactive questionnaire modal.

## Features

- 18-question HRA with conditional follow-up logic
- Visual summary with risk indicators (yellow/red highlighting)
- Side-by-side display of Physical Activities and Daily Living Activities

## Button Visibility

The "Health Risk Assessment" button appears in the note header when:

1. **Note is editable** - Note state is one of: NEW, PSH (Pushed), ULK (Unlocked), RST (Restored), UND (Undeleted), CVD (Converted)
2. **No existing HRA** - Neither the custom command (`healthRiskAssessmentSummary`) nor a questionnaire command with "Health Risk Assessment" exists on the note

The button is hidden on locked/signed notes or when an HRA has already been completed.

## Note Content

The custom command displays a formatted HTML summary:

- **General Health Card** - Self-rated health compared to others (top banner)
- **Physical Activities** - 6 activities with difficulty levels (left column)
- **Daily Living Activities** - 5 ADL items with follow-up responses (right column)

Risk indicators:
- **Yellow** - Moderate concern (e.g., "Some Difficulty", "Fair" health)
- **Red** - High concern (e.g., "A Lot of Difficulty", "Unable", "Poor" health, needs help but doesn't receive it)

The print template uses the same layout with neutral styling (no color highlighting).

## Configuration

### OUTPUT_MODE Secret

Controls what gets added to the note when the assessment is submitted.

| Value | Description |
|-------|-------------|
| `custom` | Custom command with HTML summary (default) |
| `questionnaire` | Standard questionnaire command |
| `both` | Both custom command and questionnaire |

Set via Plugin Secrets in Canvas Admin.

## Testing (UAT)

1. Open a patient chart and create a new note
2. Click "Health Risk Assessment" button in the note header
3. Complete the questionnaire - verify conditional follow-ups appear:
   - "Yes" → "Do you receive help?"
   - "Don't Know" → "Due to your health?"
   - "No" → no follow-up
4. Submit the assessment
5. Verify the summary appears in the note with the layout described above
6. Re-open the note - verify the HRA button no longer appears
