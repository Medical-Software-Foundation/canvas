drag-drop-availability
======================

## Description

A standalone, drag-and-drop **availability manager** for Canvas. Staff manage
provider and room open hours ("Available" / "Busy" blocks) on a weekly
calendar view, backed by core Canvas `Calendar` and `Event` data. It is a
focused subset of the `scheduling_with_rooms` plugin — the availability-setting
half — with the patient-facing scheduler, visit-type/room mapping, and booking
logic deliberately removed.

Use it when you want providers and rooms to express availability through a
friendly UI, but you handle booking through native Canvas scheduling (or
another tool).

## What it does

- A **Manage Availability** provider-menu app opens a weekly calendar manager.
- Pick a provider or room and a location; drag to create, move, and resize
  availability blocks.
- Blocks are stored as calendar events:
  - **Available** → the staff member's `Clinic` calendar.
  - **Busy** → the staff member's `Admin` calendar.
- Supports one-off and recurring (daily/weekly) blocks with an optional end
  date, and per-block allowed note types.

## How it works

- `AvailabilityManagerApp` (provider menu) launches the UI via a modal.
- `AvailabilityWebApp` serves the HTML/CSS/JS and the bootstrap context
  (providers, rooms, locations, note types, existing events).
- `CalendarAPI` (`POST /calendar`) creates or retrieves a `{Staff}: {Type}:
  {Location}` calendar. Retrieval binds on the **staff UUID in the calendar
  description** plus type and location, so display-name formatting (e.g. a
  credential suffix like "MD") never causes a duplicate calendar to be minted.
- `CalendarEventsAPI` (`GET/POST/PATCH/DELETE /events`) reads and writes the
  availability events. Times are stored in UTC; the UI edits in a chosen
  timezone.

## Data

Reads/writes only core Canvas `Calendar` and `Event` data — no custom-data
namespace, no FHIR, no booking side effects.

## Configuration (secrets)

| Secret | Purpose |
| --- | --- |
| `SCHEDULABLE_STAFF_ROLES` | Comma-separated staff role codes that appear in the provider dropdown (rooms, role `RR`, are always included). |
| `BRAND_PRIMARY`, `BRAND_PRIMARY_HOVER`, `BRAND_PRIMARY_TINT_BG`, `BRAND_PRIMARY_TINT_TEXT` | Optional brand colors for the UI. |
| `BRAND_FONT_STACK`, `BRAND_FONT_URL` | Optional brand font (font URL must be a Google Fonts CSS endpoint). |

## How to install

```
canvas install drag_drop_availability
```

## Tests

```
uv run pytest
```
