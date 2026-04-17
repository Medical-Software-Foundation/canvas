# provider_schedule_companion

A Canvas plugin demonstrating the **provider companion (global scope)** application type — a mobile-friendly "at-a-glance" surface for the logged-in provider. This plugin shows the provider their **own schedule** with day, week, and month views, launched from the provider companion main page.

The 3-tier provider companion harness exposes three `ApplicationScope` values:

| Scope | Surface | Context available |
|---|---|---|
| `provider_companion_global` | companion main page | (none) |
| `provider_companion_patient_specific` | patient detail page | `patient.id` |
| `provider_companion_note_specific` | inside an expanded note | `patient.id`, `note.id` |

This plugin uses `provider_companion_global` — the companion main page, not tied to any patient or note.

## What it does

- Opens in a modal (via `LaunchModalEffect`) from the companion main page.
- Queries `Appointment.objects.filter(provider__id=<logged-in staff>)` for a date range derived from the current view.
- Renders three views:
  - **Day** — the default, centered on today. Lists each appointment as a Material-style card showing time and patient name. Tap a card to reveal full detail (appointment type, reason for visit, duration, status).
  - **Week** — a vertical stack of seven day sections. Each day has a centered date label (tappable to jump into Day view for that date) and lists the day's appointments as the same tap-to-expand cards. Empty days show an italicized "No appointments". When today falls inside the visible week, the content scrolls today's section into view on render.
  - **Month** — a six-row calendar grid. Cells with appointments show a count badge; tap a cell to jump into Day view for that date.
- Prev/Next nav steps by one day, week, or month depending on the active view; the Today button snaps back to today in the current view.
- Patient names are rendered as links that break out of the modal iframe via `target="_top"` to `/companion/patient/<uuid>/`.

## Architecture

```
provider_schedule_companion/
├── CANVAS_MANIFEST.json               # plugin manifest (scope: provider_companion_global)
├── README.md                          # this file
├── LICENSE                            # MIT
├── applications/
│   └── schedule_app.py                # Application subclass; on_open → LaunchModalEffect
├── handlers/
│   └── schedule_api.py                # SimpleAPI: UI shell + JSON endpoints
├── static/
│   ├── index.html                     # SPA shell (header, view tabs, nav, content slot)
│   ├── main.js                        # vanilla-JS, no framework; view state + fetch + render
│   └── styles.css                     # mobile-first; Material-style cards w/ elevation
└── assets/
    ├── icon.png                       # 256×256 launcher icon
    └── schedule-calendar-icon.svg     # source SVG for the icon
```

### Request flow

1. Provider taps the app in the companion launcher.
2. `ScheduleApp.on_open()` returns a `LaunchModalEffect` pointing to `/plugin-io/api/provider_schedule_companion/app/`.
3. `ScheduleAPI.index()` serves `static/index.html` rendered through `render_to_string`.
4. `main.js` loads and fetches `/app/appointments?start=<iso>&end=<iso>` for the current view's range.
5. `ScheduleAPI.appointments()` runs the query, serializes, and returns JSON.
6. `main.js` renders into `#content`.

### Data access

- Read: `Appointment`, `Patient`, `NoteType` (via `Appointment.select_related("patient", "note_type")`).
- No writes.
- `data_access` in the manifest is empty because queries happen through the SDK's ORM surface, not through event subscriptions.

### Auth

- `SessionCredentials`; the endpoint rejects requests where `credentials.logged_in_user is None`.
- The logged-in staff UUID is read from the `canvas-logged-in-user-id` header (set by the platform on every request into `/plugin-io/`).

### Timezone handling

The client computes view boundaries as local `Date` objects and sends their `.toISOString()` representations (UTC). The server parses those with `datetime.fromisoformat` (`Z` suffix supported) and filters by `start_time__gte` / `start_time__lt`. Appointments come back as ISO strings; the client renders them with `toLocaleTimeString` / `toLocaleDateString` so display follows the device's locale and timezone.

## Endpoints

All mounted under `/plugin-io/api/provider_schedule_companion/app/`.

| Method & path | Purpose |
|---|---|
| `GET /` | HTML shell |
| `GET /appointments?start=<iso>&end=<iso>` | JSON list of appointments (provider = logged-in user, `start_time` in `[start, end)`) |
| `GET /main.js` | served JS |
| `GET /styles.css` | served CSS |

Appointment JSON shape:
```json
{
  "id": "…",
  "start_time": "2026-04-17T09:00:00+00:00",
  "duration_minutes": 30,
  "patient_id": "<uuid>",
  "patient_name": "Jane Doe",
  "appointment_type": "Follow-up",
  "reason_for_visit": "Back pain",
  "status": "confirmed"
}
```

## Deploy

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/provider_schedule_companion/provider_schedule_companion
```

## Test

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/provider_schedule_companion/tests \
    --cov=provider_schedule_companion --cov-branch --cov-report=term-missing
```

Current coverage: **100%** (46 stmts, 2 branches).

## Known considerations

- **Icon scale** — rendered at 256×256 because the 48×48 default for `cpa:icon-generation` looks fuzzy in the launcher.
- **Browser locale for date math** — the "today" boundary is derived from the browser clock; a user browsing in a timezone far from the practice may see off-by-day edge cases at midnight.
- **Modal scroll isolation** — `body` is a full-height flex column with `overflow: hidden`; only `#content` scrolls, so the header, view tabs, and date nav stay pinned.

## License

MIT. See [LICENSE](./LICENSE).
