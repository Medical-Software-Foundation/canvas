commit_all_commands_button
==========================

## Description

The `commit_all_commands_button` plugin for Canvas adds a button to the footer of every clinical note. When clicked, this button will automatically commit all uncommitted commands within the note. This streamlines workflows for clinicians and staff by allowing them to commit commands in a single click rather than committing each command individually.

## Trigger

**User-triggered:** The plugin adds an action button to the note footer. Users click the button to commit all staged commands in the current note.

## Effects

When the button is clicked, the plugin:
1. Queries all staged (uncommitted) commands in the current note
2. Creates a commit effect for each command
3. Returns all commit effects, which commits the commands in Canvas

## How It Works

- The plugin adds a button labeled **"Commit All Commands"** to the note footer.
- When the button is pressed, the plugin finds all commands in the current note that are not yet committed.
- The plugin creates commit effects for each staged command, causing them to be committed.

## Configuration Requirements

**SDK Commands Switch:** The SDK commands switch must be turned on in Canvas for each command type you want the button to commit. Without this setting enabled, the button will not be able to commit those command types.

## Supported Command Types

The following 27 command types can be committed with this button (when SDK commands are enabled):

- Allergy
- Assess
- Change Medication
- Close Goal
- Consult Report Review
- Diagnose
- Family History
- Follow Up
- Goal
- History Of Present Illness
- Imaging Review
- Immunization Statement
- Instruct
- Lab Review
- Medical History
- Medication Statement
- Past Surgical History
- Perform
- Plan
- Physical Exam
- Questionnaire
- Remove Allergy
- Resolve Condition
- Review Of Systems
- Stop Medication
- Structured Assessment
- Task
- Uncategorized Document Review
- Update Diagnosis
- Update Goal
- Vitals

## Installation & Usage

1. Add this plugin to your Canvas instance using the `canvas install commit_all_commands_button` command.
2. Open any clinical note in Canvas. You will see the **"Commit All Commands"** button in the note footer.
3. Click the button to commit all uncommitted commands in the note at once.

## External Dependencies

None. This plugin uses only Canvas SDK functionality and does not require external APIs or services.
