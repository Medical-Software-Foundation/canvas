# Default Supervising Provider

A reference plugin that defaults a note's **supervising provider** from the
rendering provider's Staff record when the note is created.

## Why this is a plugin

Canvas deliberately does **not** auto-populate `Note.supervising_provider` from
`Staff.default_supervising_provider`. Defaulting behavior is left to customers so
they stay in control of when and how it happens. This plugin is the reference
implementation of that pattern — install it as-is, or fork/adapt it.

## What it does

On `NOTE_CREATED`:

1. Loads the note and its rendering `provider`.
2. Reads `provider.default_supervising_provider` (a Staff field configured per
   provider in Canvas).
3. If a default is set **and** the note has no supervising provider yet, writes
   it to `note.supervising_provider` via the Note effect.

It never overrides a supervising provider that is already set on the note, and it
does nothing when the provider has no `default_supervising_provider`.

## How to adapt it

The logic lives in `default_supervising_provider/handlers/default_supervising_provider.py`.
Common changes:

- **Only default for certain note types** — check `note.note_type_version` before
  emitting the effect.
- **Always overwrite** — remove the `note.supervising_provider_id` guard.
- **Different source** — derive the supervising provider from your own rule
  instead of `default_supervising_provider`.

## Requirements

Needs the Canvas SDK support for the supervising provider added in KOALA-5587
(`Staff.default_supervising_provider` and the Note effect's
`supervising_provider_id`). Until that ships in a released `canvas` version, the
`pyproject.toml` pins the SDK to the `feat/sdk-supervising-provider` branch —
revert that pin to a released version once available.

## Tests

```
uv run pytest
```
