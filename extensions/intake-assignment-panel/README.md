# Intake Assignment Panel

A provider-menu Canvas application that surfaces pending intake notes, filtered by the logged-in clinician's active state licenses, so providers can triage only the work they're licensed to handle.

## What it does

Adds a top-level "Intake Assignment Panel" item to the provider menu. Opening it shows a sortable table of every pending intake note in the instance whose patient lives in a state where the logged-in clinician holds an active license. Each row deep-links to the unsigned note in the patient's chart.

A "pending intake" is any unsigned note whose Note Type name matches one of the names configured in the `INTAKE_NOTE_TYPES` secret.

## Problem it solves

In multi-state telehealth practices, a queue of unsigned intake notes typically lands in front of every clinician at once — even though each clinician can only see patients in the specific states where they're licensed. Clinicians have to scan the full queue and skip past work they can't legally take, which slows triage and leaves intakes lingering.

This plugin filters the queue server-side using each clinician's `StaffLicense` records, so the panel only shows the intakes that clinician is licensed to pick up.

## Who it's for

Multi-state telehealth and digital-health practices on Canvas where:

- Multiple clinicians share a single pool of pending intake notes, and
- Clinicians are licensed in different (and overlapping) subsets of US states.

If every clinician in your practice is licensed in the same states, you don't need this plugin.

## How it works

- When a staff member opens the panel:
  - If they have one or more **active** (non-expired) state licenses on their Staff profile, the panel shows only pending intakes whose patient's home-address state matches one of their licensed states.
  - If they have **zero** active licenses on file, the panel shows all pending intakes unfiltered (so admin/triage staff aren't accidentally locked out).
- Rows are sortable by Patient name, State, and Time pending. Default sort is oldest pending first.
- Clicking a row opens the unsigned note in a new tab.

## How to install

```bash
canvas install intake-assignment-panel
```

Then configure the two required secrets below.

## Configuration

Two secrets are required:

| Secret | Required | Description |
|---|---|---|
| `INTAKE_NOTE_TYPES` | Yes | Comma-separated list of Note Type names to treat as "intake" (case-insensitive match). Example: `New Patient Intake, Follow-up Intake` |
| `CANVAS_INSTANCE_URL` | Yes | Canvas instance base URL, used to construct the deep-link to each unsigned note. Example: `https://example.canvasmedical.com` |

State licenses do not require configuration — the plugin reads them from each Staff member's `StaffLicense` records and only considers licenses where `license_type = STATE_LICENSE` and `expiration_date >= today`.

## Screenshots

_Screenshots to be added in a follow-up — the panel renders a single sortable table of pending intakes with a banner showing the licensed-state filter applied._

## Running tests

```bash
uv run pytest tests/
```
