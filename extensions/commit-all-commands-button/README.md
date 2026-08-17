commit_all_commands_button
==========================

## Description

The `commit_all_commands_button` plugin for Canvas adds a button to the footer of every clinical note. When clicked, this button will automatically commit all uncommitted commands within the note. This streamlines workflows for clinicians and staff by allowing them to commit commands in a single click rather than committing each command individually.

## Trigger

**User-triggered:** The plugin adds an action button to the note footer. Users click the button to commit all staged commands in the current note.

The button only appears when there is actually something for it to do — see [When the Button Appears](#when-the-button-appears).

## Effects

When the button is clicked, the plugin:
1. Queries all staged (uncommitted) commands in the current note
2. Creates a commit effect for each command it knows how to commit
3. Appends a `ReloadNoteActionButtonsEffect` so the note re-evaluates its buttons
4. Returns all effects, which commits the commands in Canvas

## When the Button Appears

The button is shown only if **both** are true:

- The note is not locked.
- The note has at least one staged command of a [supported type](#supported-command-types).

The second condition is scoped to the supported types deliberately. A note holding only commands this button can't commit — an unsent Prescribe, say — would otherwise show a button that does nothing when clicked.

After a commit run, the plugin returns a [`ReloadNoteActionButtonsEffect`](https://docs.canvasmedical.com/sdk/effect-reload-action-buttons/) for the note. Committing empties the staged set, so the button's own visibility condition no longer holds, and the reload makes it disappear immediately rather than lingering until the next page load.

The reload is only requested when at least one command was actually committed. If nothing committed — nothing staged, or every command failed validation — visibility can't have changed, so the round trip is skipped.

## How It Works

- The plugin adds a button labeled **"Commit All Commands"** to the note footer, visible under the conditions above.
- When the button is pressed, the plugin finds all commands in the current note that are not yet committed.
- The plugin creates commit effects for each staged command, causing them to be committed.
- Commands it has no mapping for are logged and skipped rather than failing the run.
- A button reload is appended last, so it re-evaluates visibility against the post-commit state.

## Configuration Requirements

**SDK Commands Switch:** The SDK commands switch must be turned on in Canvas for each command type you want the button to commit. Without this setting enabled, the button will not be able to commit those command types.

## Supported Command Types

The following 32 command types can be committed with this button (when SDK commands are enabled):

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
- POC Lab Test
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

## Commands This Button Does Not Commit

Not every command is a candidate, and the reasons differ. This section exists so the omissions read as deliberate rather than as gaps waiting to be filled — if you are here to add a command, check which group it falls into first.

### Orders — they have to be sent, not just committed

Committing these would leave an order that looks complete but was never transmitted. Sending is a separate, deliberate step that belongs to the provider.

- Prescribe
- Refill
- Adjust Prescription
- Imaging Order
- Lab Order

### Refer — it carries a delegate

A staged Refer does not mean the provider intended to commit it. The delegate makes the provider's intent ambiguous, so committing it in bulk could act on something they were still deciding.

### Reason for Visit — it is always staged

RFV stays staged by design and is never committed, so there is nothing for this button to do. Consistent with that, its `COMMIT_REASON_FOR_VISIT_COMMAND` interpreter registration is commented out in home-app, so the effect would not be honored even if it were mapped.

### Reference — it is committed on origination

A Reference command is already committed by the time it exists, so it never appears in the staged set this button queries. Mapping it would be dead code.

### Reviewed and Custom Command — no commit effect exists

`ChartSectionReviewCommand` ("Reviewed") and `CustomCommand` are in the SDK but have no `COMMIT_*` effect defined, so they cannot be committed by any plugin.

### Not in the SDK

These are Canvas commands with no SDK equivalent, so a plugin cannot act on them at all: Adjust Protocol, Approve Change, Deny Change, Visual Exam Finding, Immunize, Clipboard, Educational Material, Private Notes, Snooze Protocol, and the coding gap commands (Assess, Create, Defer, Validate).

## Installation & Usage

1. Add this plugin to your Canvas instance using the `canvas install commit_all_commands_button` command.
2. Open any clinical note in Canvas. You will see the **"Commit All Commands"** button in the note footer.
3. Click the button to commit all uncommitted commands in the note at once.

## External Dependencies

None. This plugin uses only Canvas SDK functionality and does not require external APIs or services.
