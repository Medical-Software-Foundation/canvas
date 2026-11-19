conditional_questionnaire
=========================

## Description

Questionnaire Builder lets you add **Field Rules** to a question so it only shows when an
earlier answer calls for it, and the builder's Preview tab shows that branching. A
Questionnaire command added to a note shows every question, whatever the rules say.

This plugin adds a **Conditional Questionnaire** button to the note header. It opens a
form beside the note where the provider:

1. Picks any active questionnaire that can be added in charting.
2. Fills it in. Questions show and hide as they answer, following the Field Rules the
   same way the builder's Preview tab does.
3. Clicks **Save to note**. The plugin adds a committed Questionnaire command to the note
   with the answers to the questions that showed. An answer to a hidden question is
   never saved, even if it was filled in before the question was hidden.

### How Field Rules are read

| Rule | Shows the question when |
|------|-------------------------|
| `=` an option | that option is picked |
| `!=` an option | the controlling question is answered with something else |
| `exists` | the controlling question has any answer |
| `not_exists` | the controlling question has no answer |
| ALL (or not set) | every condition holds |
| ANY | at least one condition holds |

A hidden question counts as unanswered, so hiding one question also hides every question
that depends on it (chains collapse). A rule that compares to text instead of an option
matches an option's name, code or value, ignoring case. A rule this plugin can't read
(an unknown operator, or one that points at a question not on the questionnaire) is
ignored, so the question shows rather than being hidden for good.

A hidden question keeps what was typed, so switching the earlier answer back brings it
back; it is only left out when saving. Answers not yet saved are kept in this browser tab
(sessionStorage) and come back if the form is closed and reopened on the same note; they
are cleared once saved and when the tab closes.

## Setup

Install the plugin. There is nothing to configure: the button shows on every note that can
still be edited (it is hidden on locked and signed notes), and the picker lists every active
questionnaire with "can originate in charting" turned on.

## Access

Every endpoint needs a signed-in staff session; patients and outside callers get nothing.
Any signed-in staff member can open the form on a note they can see and save a questionnaire
to it. The plugin reads questionnaires and notes and writes only the Questionnaire command.
It logs ids and counts, never answers.

## Limitations

- **Integer and decimal questions can't be saved through the form yet.** This is a limit of
  the Canvas SDK's Questionnaire command, not of this plugin:
  - Integer questions show in the form but can't be answered there, because the command
    refuses integer answers when it is applied. Save the questionnaire, then answer those
    questions in the note.
  - The SDK can't build a Questionnaire command for a questionnaire with a decimal (or
    other unsupported) question, so the form shows a notice and won't save it.
- The committed command in the note is the standard Questionnaire command, so it still
  lists every question; hidden questions are simply left blank.
- The button only shows on notes that can be edited. If a note is locked while the form is
  open, saving is refused with a message asking to unlock the note.

## Development

```bash
uv sync
uv run pytest --cov
```
