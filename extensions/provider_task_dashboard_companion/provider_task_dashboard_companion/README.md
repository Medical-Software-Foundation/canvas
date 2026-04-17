# provider_task_dashboard_companion

A Canvas plugin demonstrating the **provider companion (global scope)** application type — a mobile-friendly task triage surface launched from the provider companion main page. Providers can browse the practice's tasks with filters for status and label, drill into a task to read and post comments, assign a task to themselves, or mark a task they own complete.

See the sibling `provider_schedule_companion` README for background on the three provider companion scopes; this plugin uses `provider_companion_global`.

## What it does

- Opens in a modal (via `LaunchModalEffect`) from the companion main page.
- Lists tasks from the practice with three filter dimensions:
  - **"Assigned to me"** toggle (default on). When off, the full practice task list is visible.
  - **Status** multi-select chips — `OPEN` (default), `COMPLETED`, `CLOSED`.
  - **Label** multi-select chips, populated from active `TaskLabel`s that include `"tasks"` in `modules`.
- Each task card shows title, status, due date (with an "overdue" highlight for open tasks past due), patient name (as a `target="_top"` link to `/companion/patient/<uuid>/`), the task's labels, and — when the list query is not filtered to "mine" — the assignee name, with "Unassigned" when no one is assigned.
- A collapsed card with ≥1 comment displays an italicized "_N comments_" line; a task with zero comments shows no comment indicator.
- Tapping a card expands the detail drawer, which loads the task's comment thread on demand and exposes:
  - A composer that posts a new `TaskComment` (optimistically appended to the thread on success).
  - An **Assign to me** button when the current user is not the assignee.
  - A **Mark complete** button when the current user is the assignee and status is OPEN.
- All write operations are emitted as SDK effects (`AddTaskComment`, `UpdateTask`) so the platform performs the mutation.

## Architecture

```
provider_task_dashboard_companion/
├── CANVAS_MANIFEST.json               # plugin manifest (scope: provider_companion_global)
├── README.md                          # this file
├── LICENSE                            # MIT
├── applications/
│   └── task_dashboard_app.py          # Application subclass; on_open → LaunchModalEffect
├── handlers/
│   └── task_dashboard_api.py          # SimpleAPI: UI shell + JSON + POST endpoints
├── static/
│   ├── index.html                     # SPA shell (filter bar + task list slot)
│   ├── main.js                        # vanilla-JS; filter state, fetch, expand, compose
│   └── styles.css                     # Material-style cards matching schedule companion
└── assets/
    ├── icon.png                       # 256×256 launcher icon
    └── task-clipboard-icon.svg        # source SVG for the icon
```

### Request flow

1. Provider taps the app in the companion launcher.
2. `TaskDashboardApp.on_open()` returns a `LaunchModalEffect` pointing to `/plugin-io/api/provider_task_dashboard_companion/app/`.
3. `TaskDashboardAPI.index()` serves `static/index.html`.
4. `main.js` loads and:
   - `GET /app/filters` for label + status options.
   - `GET /app/tasks?mine=…&statuses=…&labels=…` for the filtered list.
5. Tapping a card triggers `GET /app/tasks/<id>` to load the task detail + comments.
6. Posting a comment / assigning / completing calls the appropriate `POST` endpoint, which returns the applied effect alongside a `202 Accepted`.

### Data access

- Reads: `Task`, `TaskLabel`, `TaskComment`, `Staff`, `Patient` (via `select_related("assignee", "patient")` + `prefetch_related("labels")` on the task list).
- The list query uses `.annotate(comment_count=Count("comments"))` so each card can show the comment count without per-row queries.
- Writes are all effect-based — the plugin never calls `.save()` itself, which is necessary because the plugin sandbox forbids direct ORM writes.
- No `data_access` declarations required in the manifest; SDK ORM reads and effect emissions are the access surface.

### Auth

- `SessionCredentials`; the endpoint rejects requests where `credentials.logged_in_user is None`.
- The logged-in staff UUID is read from the `canvas-logged-in-user-id` header.
- Server-side checks enforce that only the task's assignee can mark it complete — the client uses the server-set `can_complete` / `can_assign_to_me` flags to show/hide buttons, but the `POST /complete` handler re-verifies before emitting the effect.

## Endpoints

All mounted under `/plugin-io/api/provider_task_dashboard_companion/app/`.

| Method & path | Purpose |
|---|---|
| `GET /` | HTML shell |
| `GET /filters` | JSON: `{statuses: […], labels: [{id, name, color}, …]}` |
| `GET /tasks?mine=0|1&statuses=CSV&labels=CSV` | JSON list of serialized tasks |
| `GET /tasks/<task_id>` | JSON: `{task: {…}, comments: [{…}, …]}` |
| `POST /tasks/<task_id>/comments` | body `{body: "…"}`; emits `AddTaskComment` |
| `POST /tasks/<task_id>/complete` | 403 unless caller is the assignee; emits `UpdateTask(status=COMPLETED)` |
| `POST /tasks/<task_id>/assign-to-me` | emits `UpdateTask(assignee_id=<caller>)` |
| `GET /main.js`, `GET /styles.css` | served static assets |

Task JSON shape:
```json
{
  "id": "…",
  "title": "Call pharmacy about refill",
  "status": "OPEN",
  "due": "2026-04-17T15:00:00+00:00",
  "assignee_id": "<uuid>",
  "assignee_name": "Alex Park",
  "patient_id": "<uuid>",
  "patient_name": "Jane Doe",
  "labels": [{"id": "…", "name": "Urgent", "color": "red"}],
  "comment_count": 3,
  "is_mine": true,
  "can_complete": true,
  "can_assign_to_me": false
}
```

Comment JSON shape:
```json
{
  "id": "…",
  "body": "Left voicemail at 3pm.",
  "created": "2026-04-17T15:12:04+00:00",
  "creator_name": "Alex Park"
}
```

## Deploy

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/provider_task_dashboard_companion/provider_task_dashboard_companion
```

## Test

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/provider_task_dashboard_companion/tests \
    --cov=provider_task_dashboard_companion --cov-branch --cov-report=term-missing
```

Current coverage: **100%** (111 stmts, 14 branches).

## Known considerations

- **Eventual consistency** — effects are applied asynchronously by the platform, so the `GET /tasks` refetch that runs after "Assign to me" or "Mark complete" may briefly still show the pre-change state. The optimistic UX (append comments client-side; refetch on action) papers over the gap in practice but isn't a strong consistency guarantee.
- **FK filter by UUID** — `Appointment.provider_id` / `Task.assignee_id` target the integer `dbid` primary key, not the public UUID. The filters in this plugin use the double-underscore traversal form (`assignee__id=<uuid>`) to hit the UUID field instead.
- **Staff-only** — currently all endpoints assume `logged_in_user` is a staff UUID. Patient-side sessions are not supported (nor relevant for a provider companion surface).

## License

MIT. See [LICENSE](./LICENSE).
