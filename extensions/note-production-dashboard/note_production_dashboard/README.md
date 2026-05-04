note-production-dashboard
=========================

A staff-facing dashboard that surfaces locked-note counts per provider over a
selectable Daily / Weekly / Monthly window, with drill-in to the per-provider
note list (patient, date-time of service, CPT codes, note type, reason for
visit).

## Components

- **`NoteProductionDashboardApp`** (Application, scope `provider_menu_item`).
  Adds a "Note Production Dashboard" item to the top of the provider menu.
  Clicking it opens the dashboard as a full-page view via `LaunchModalEffect`.

- **`NoteProductionDashboardAPI`** (SimpleAPI). Three GET endpoints, all
  staff-session authenticated via `StaffSessionAuthMixin`:
  - `/dashboard` — single-page HTML dashboard (vanilla JS, no build step).
  - `/providers?period={daily|weekly|monthly}&week_start={sunday|monday}` —
    JSON list of providers with their locked-note counts in the window.
  - `/providers/<provider_id>/notes?period=…&week_start=…` — JSON note rows
    for a single provider.

## Period semantics

- **Daily** — today 00:00 → tomorrow 00:00.
- **Weekly** — this calendar week, anchored on the requested `week_start`
  (default Sunday; selectable in the UI and persisted in `localStorage`).
- **Monthly** — this calendar month, 1st 00:00 → 1st of next month 00:00.

The right edge of each window is end-of-period, not "now" — counts include
notes already locked later in the period.

## Scope of "locked"

A note is included when its current `CurrentNoteStateEvent.state` is one of
`LOCKED`, `RELOCKED`, or `SIGNED`. (Locking a note in Canvas auto-progresses
through `LKD → SGN`, so most locked notes settle on `SGN`.)

## Configuration

No secrets, no plugin settings. Audience is all logged-in staff — there is no
role or team gate. Times are formatted in UTC; the `_SettingsShim` constant in
`handlers/dashboard_api.py` can be replaced with a plugin secret if per-instance
localized times become necessary.
