# Plugin Specification: note-production-dashboard

## Goal

A performance-tracking dashboard that surfaces, per provider, the locked notes they have authored ("note production") over a selectable time window (today / this calendar week / this calendar month). Clicking a provider drills into the list of their individual notes with patient, date-time of service, CPT codes, note type, and reason-for-visit details.

## Audience & access

- **Audience:** All staff (any logged-in Canvas user). No admin/role gate.
- **Surface:** Custom item in the provider menu. Implemented as a Canvas `Application` with `scope: "provider_menu_item"` (`menu_position: "top"`). Clicking the menu item opens the dashboard as a full-page view inside Canvas.

## Time periods

The dashboard offers three calendar-aligned views, switched via a top-of-page toggle. All time math is performed in the instance's timezone.

| Toggle | Range |
| --- | --- |
| **Daily** | Today, 00:00 (local) → 24:00 (local) |
| **Weekly** | This calendar week — week-start 00:00 → following week-start 00:00 |
| **Monthly** | This calendar month — 1st of the month 00:00 → 1st of next month 00:00 |

**Week start is user-selectable.** A small "Week starts:" toggle (Sunday / Monday) sits next to the period toggle. Default is **Sunday**. The selection persists across sessions via `localStorage`, and is sent to the server as a query param (e.g., `?week_start=sunday`). The server uses it to compute the Weekly window's edges. The Daily and Monthly windows are unaffected by this setting.

The right edge of each window is the end of the period, not "now" — so the Weekly count includes notes already locked later this week. (If you'd prefer the windows to clamp to "now" so future days don't appear empty, flag it.)

## Scope of "notes"

Only **locked** notes count. A note is considered locked when its current `CurrentNoteStateEvent.state` is `NoteStates.LKD` (or `RLK` — relocked counts as locked again). Unlocked, deleted, draft, recalled, scheduled, booked, canceled, no-show, and reverted notes are excluded.

`datetime_of_service` is used as the time the work happened (not `created` / `modified`).

## Layout

Two-pane layout:

```
┌────────────────────────────────────────────────────────────────────────┐
│  [ Daily ] [ Weekly ] [ Monthly ]      Week starts: [ Sun ] [ Mon ]    │
├──────────────────┬─────────────────────────────────────────────────────┤
│ Providers        │  Notes for: Dr. Jane Smith (Weekly)                 │
│ ───────────────  │  ─────────────────────────────────────────────────  │
│ ▸ Smith, Jane 24 │  Patient    │ Time         │ CPT      │ Type │ RFV │
│   Lee, Wei    18 │  ───────────┼──────────────┼──────────┼──────┼──── │
│   Patel, Anya 12 │  Doe, John  │ 04/27 09:30  │ 99213    │ OV   │ ... │
│   ...            │  Roe, Jane  │ 04/27 10:15  │ 99214,   │ OV   │ ... │
│                  │              │              │ 90834    │      │     │
│                  │  ...                                                │
└──────────────────┴─────────────────────────────────────────────────────┘
```

- **Left pane:** vertical list of providers who have locked at least one note in the selected period, with a count badge. Sorted by count desc, then by provider name. The selected provider is highlighted; the first provider is selected by default on load.
- **Right pane:** table of the selected provider's notes for the selected period. Columns: Patient, Date-time of service, CPT codes, Note type, Reason for visit. Sorted by `datetime_of_service` desc.

Switching the time toggle refreshes both panes. Selecting a different provider only refreshes the right pane.

## Data sources & mapping

Per note row:

| Column | Source |
| --- | --- |
| Patient | `Note.patient.first_name + " " + Note.patient.last_name` |
| Date-time of service | `Note.datetime_of_service` (formatted in instance timezone) |
| CPT codes | `Note.billing_line_items.filter(status=BillingLineItemStatus.ACTIVE)` → `cpt` field, comma-joined |
| Note type | `Note.note_type_version.name` |
| Reason for visit | The **first** `ReasonForVisitCommand` attached to the note (earliest-added). Use the structured RFV's coding `display` / `text` if present; otherwise the unstructured text. If no RFV command is on the note, render an em-dash. |

Per provider entry:

| Field | Source |
| --- | --- |
| Provider name | `Note.provider` (Staff) — `first_name + " " + last_name`, plus `, {credentials}` when the Staff record has credentials populated (e.g., "Jane Smith, MD") |
| Note count | Number of locked notes by this provider in the selected period |

Locked notes query (sketch):

```python
# All notes whose current state is LKD or RLK in the period
locked_state_events = CurrentNoteStateEvent.objects.filter(
    state__in=[NoteStates.LKD, NoteStates.RLK],
    note__datetime_of_service__gte=start,
    note__datetime_of_service__lt=end,
).select_related("note__provider", "note__patient", "note__note_type_version")
```

## Architecture

Two handlers in one plugin:

1. **`Application` handler** (`provider_menu_item` scope)
   - On `on_open()`, returns a `LaunchModalEffect` with `target=LaunchModalEffect.TargetType.PAGE` pointing at the plugin's SimpleAPI dashboard URL.

2. **`SimpleAPI` handler** serving:
   - `GET /dashboard` — returns the dashboard HTML (single-page, vanilla JS — no build step). The page reads the `period` from a query param (default `daily`) and fetches data via the JSON endpoints.
   - `GET /providers?period={daily|weekly|monthly}` — returns `[{ provider_id, name, count }, ...]`, sorted by count desc.
   - `GET /providers/<provider_id>/notes?period={daily|weekly|monthly}` — returns the notes table rows for that provider in that period.

   **Auth:** SimpleAPI endpoints will require an authenticated Canvas session. Because this dashboard is a server-rendered page loaded inside Canvas via `LaunchModalEffect`, the session cookie travels with the iframe request. Endpoints will use the staff-session authentication pattern (`StaffSessionAuthMixin` or equivalent — to be confirmed against the SDK during implementation). No API keys, no patient-scoped tokens.

## Out of scope

- Date-range pickers / custom ranges (only current-day/week/month toggles).
- Navigating to past or future periods (no prev/next arrows).
- Export to CSV / Excel.
- Drilling into a specific note (no row click navigation).
- Filtering by note type, location, or service line.
- Charts / graphs / trends — counts and a flat table only.
- Provider role/permission gating (everyone sees everything).

## Empty state

When the selected period has zero locked notes:
- Left pane: render a single line "No locked notes in this period".
- Right pane: render the same message in place of the table.

## Plugin name

`note-production-dashboard` (kebab-case; describes function).
