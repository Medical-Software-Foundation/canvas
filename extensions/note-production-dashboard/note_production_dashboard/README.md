# note-production-dashboard

A staff-facing dashboard that surfaces locked-note counts per provider over a selectable Daily / Weekly / Monthly window, with drill-in to the per-provider note list (patient, date-time of service, CPT codes, note type, reason for visit).

## The problem this solves

Practice operations need an at-a-glance answer to *"how many notes did each provider lock today / this week / this month, and what were they?"*. Without a dedicated view, that question normally requires either an ad-hoc database query or a brittle export-and-spreadsheet workflow — neither of which is fast, repeatable, or available to non-engineers.

This plugin answers the question directly inside Canvas, with a two-pane UI:

- **Left pane** — every provider that has at least one locked note in the selected window, sorted by count (descending), with a count badge.
- **Right pane** — for the selected provider, the actual notes: patient (Last, First), date/time of service, CPT codes, note type, and reason for visit. Clickable column sorting on Patient and Date/Time.

A toggle at the top of the page switches between Daily, Weekly, and Monthly windows. The week start (Sunday vs. Monday) is a separate toggle and is persisted per-browser in `localStorage`.

## Who it's for

- **Practice managers and operations leads** who track provider throughput on a daily / weekly / monthly cadence.
- **Billing and revenue-cycle staff** who need to see locked notes (and their CPTs) without opening each chart individually.
- **Providers** who want a quick read on their own production for the current period.

The dashboard surfaces every locked note for every provider — there is no per-row redaction or role-based filter. Authorization is the standard Canvas staff session: anyone with a logged-in staff account can open the dashboard.

## Installation

No environment variables, secrets, or external services are required.

```sh
canvas install --host <host> \
    /path/to/extensions/note-production-dashboard/note_production_dashboard
```

After install, a **"Note Production Dashboard"** item appears at the top of the provider menu (left rail). Clicking it opens the dashboard as a full-page modal.

## Configuration

There are **no plugin settings or secrets**. Two implicit configuration points exist:

| Concern | Default | How to change it |
|---|---|---|
| Time zone for window edges and date-of-service formatting | `UTC` | Replace the `_SettingsShim.TIME_ZONE` constant in `handlers/dashboard_api.py` with a plugin secret read, or inject a different value (the test suite already does this via monkeypatch). |
| Week start | Sunday | The user toggles Sun / Mon in the top bar; the choice is persisted per-browser in `localStorage` under the key `npd_week_start`. |

If per-instance localized times become a real requirement (rather than a one-off), the recommended path is to add a plugin secret named `TIME_ZONE` and read it inside the handler instead of editing the shim.

---

## For developers

### Components

- **`NoteProductionDashboardApp`** (Application, scope `provider_menu_item`). Adds the menu item and emits `LaunchModalEffect` on click.
- **`NoteProductionDashboardAPI`** (SimpleAPI, all routes guarded by `StaffSessionAuthMixin`):
  - `GET /dashboard` — single-page HTML dashboard.
  - `GET /main.js` — dashboard JavaScript (`text/javascript`).
  - `GET /styles.css` — dashboard CSS (`text/css`).
  - `GET /providers?period={daily|weekly|monthly}&week_start={sunday|monday}` — JSON list of providers with their locked-note counts in the window.
  - `GET /providers/<provider_id>/notes?period=…&week_start=…` — JSON note rows for a single provider.

The HTML, JS, and CSS live in `note_production_dashboard/static/` and are loaded with `canvas_sdk.templates.render_to_string`. The JS is a plain static asset; per-request state (period, week start, cache-bust token) is passed to it via `<body data-*>` attributes the JS reads from `document.body.dataset`.

### Period semantics

- **Daily** — today 00:00 → tomorrow 00:00.
- **Weekly** — this calendar week, anchored on the requested `week_start` (default Sunday).
- **Monthly** — this calendar month, 1st 00:00 → 1st of next month 00:00.

The right edge of every window is end-of-period, not "now" — counts include notes that are locked later in the same period.

### What counts as "locked"

A note is included when its current `CurrentNoteStateEvent.state` is one of `LOCKED`, `RELOCKED`, or `SIGNED`. (Locking a note in Canvas auto-progresses through `LKD → SGN`, so most locked notes settle on `SGN`.)

### Testing

```sh
cd extensions/note-production-dashboard && uv run pytest tests/ \
    --cov=note_production_dashboard --cov-report=term-missing
```

Coverage is 100% for the pure-Python paths. The two ORM-touching helpers (`_fetch_locked_state_events`, `_fetch_provider_counts`) are excluded with `# pragma: no cover` — they are patched in every endpoint test and verified end-to-end against a live database during smoke testing.

## License

MIT. See [LICENSE](../LICENSE).
