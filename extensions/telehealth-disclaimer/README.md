# Telehealth Disclaimer

## What it does

Automatically inserts a telehealth disclaimer into the **Plan** section of a note the moment a
telehealth visit note is created. The disclaimer is added as a `TelehealthDisclaimer` command so
it renders on screen and in the printed/PDF note alongside the rest of the plan.

- **Responds to:** `NOTE_STATE_CHANGE_EVENT_CREATED`
- **Triggers when:** the note is newly created (`state == "NEW"`) **and** its note type is flagged
  `is_telehealth`.
- **Effect:** originates a `telehealthDisclaimer` custom command in the plan section containing the
  disclaimer text.

Notes that are not telehealth, and events that are not the initial creation, are ignored.

## Problem it solves

Telehealth encounters typically require a documented attestation (modality, consent, identity
verification, standard of care). Relying on clinicians to paste this language into every
telehealth note by hand is error-prone and inconsistent. This plugin guarantees the attestation is
present on every telehealth note automatically, without changing the clinician's workflow.

## Who it's for

Any Canvas organization that conducts telehealth visits and wants consistent, automatic disclaimer
documentation. The disclaimer wording is configurable, so practices can supply their own
attestation/legal language.

## How to install

```bash
canvas install telehealth-disclaimer
```

Post-install requirements:

- The target Canvas instance must have at least one **note type flagged `is_telehealth`**;
  otherwise the disclaimer never triggers.
- Optionally configure the disclaimer wording (see Configuration options below). With no
  configuration, a sensible default attestation is used.

## Configuration options

| Secret | Required | Effect |
|--------|----------|--------|
| `TELEHEALTH_DISCLAIMER_TEXT` | No | Overrides the disclaimer body text with your organization's language. When unset or blank, a default attestation is used. Inserted as plain text (HTML-escaped) under the "Telehealth Disclaimer" heading. |

## Screenshots or screen recordings

<!-- TODO: Add at least one screenshot showing the Telehealth Disclaimer command in the Plan section of a telehealth note. -->

## Running tests

```bash
uv run pytest tests/
```
