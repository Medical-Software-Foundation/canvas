# Automated PHQ-9 Follow-up

## What it does

Automates the PHQ-2 to PHQ-9 escalation. When a PHQ-2 questionnaire (LOINC `58120-7`) is committed with a score greater than 2, the plugin originates a PHQ-9 questionnaire command (LOINC `44249-1`) in the same note and pulls forward the answers to the questions the two instruments share, so the clinician only fills in what is new.

## Problem it solves

A positive PHQ-2 should trigger a PHQ-9, but adding and partially re-answering the longer instrument by hand is slow and easy to skip. This makes the escalation happen automatically and carries over the overlapping responses, reducing clicks and missed follow-ups for depression screening.

## Who it's for

Primary care and behavioral health teams that screen for depression with the PHQ-2 / PHQ-9 stepped approach and want the follow-up assessment created for them at the point of care.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install phq9_followup
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

No plugin settings. The behavior is automatic once installed.

Requirements:

- The `questionnaire` command switch must be enabled on the instance.
- Both questionnaires must exist on the instance with their standard LOINC codes: PHQ-2 = `58120-7`, PHQ-9 = `44249-1`.
- The PHQ-9 questionnaire must be configured to originate in charting (`can_originate_in_charting`).
- The score threshold for escalation (greater than 2) is fixed in code.

## Screenshots or screen recordings

_Screenshots pending. After a PHQ-2 with a score above 2 is committed, a PHQ-9 command appears in the same note with shared answers pre-filled._
