team-red-template
=================

## Description

Automatically populates telehealth visit notes with a detailed History of Present Illness (HPI) and standard documentation commands when a structured reason for visit is entered.

This plugin streamlines telehealth documentation by auto-inserting a comprehensive note template that includes:
- **Detailed HPI** with patient demographics (name, age, DOB, sex at birth) and reason for visit with coding
- **Review of Systems** (blank)
- **PHQ-9 Mental Health Questionnaire**
- **Physical Exam** (blank)
- **Patient Instructions** (blank)

## Behavior

The plugin listens for the `REASON_FOR_VISIT_COMMAND__POST_ORIGINATE` event and automatically triggers when:
1. A reason for visit is entered in a note
2. The note type is "Telehealth visit" or "Telemedicine visit"
3. The note doesn't already have an HPI command (prevents duplicates)

### Example HPI Format

```
Jane Doe is a 35 year old female (DOB: 03/15/1989) who presents today for: Hypertension (SNOMED: 38341003)
```

## Installation

```bash
canvas install team-red-template
```

## Customization

To customize this plugin for your organization:

1. **Add/Modify Note Types**: Edit the `TELEHEALTH_NOTE_TYPES` tuple in `telehealth_note_template.py:33` to include additional note type names
2. **Change Commands**: Modify the `compute()` method to add, remove, or reorder commands
3. **Customize HPI Format**: Edit the narrative template in `telehealth_note_template.py:157-160`

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
