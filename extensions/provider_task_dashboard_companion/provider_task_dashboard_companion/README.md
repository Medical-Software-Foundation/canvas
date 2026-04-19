# provider_task_dashboard_companion

A mobile-friendly task triage surface that lives on the provider companion main page. Lets the logged-in provider browse the practice's tasks with filters, read and post comments, assign tasks to themselves, and mark their own tasks complete.

## What providers see

An icon titled **Task Dashboard** appears in the provider companion launcher. Tapping it opens a modal with a filter bar at the top and a scrollable list of task cards below.

Each task card shows:

- Title and a status pill (Open / Completed / Closed).
- Due date, with an "overdue" highlight for open tasks past due.
- The patient's name (if the task is linked to a patient) rendered as a link that leaves the modal to open that patient's companion page.
- The task's labels, if any.
- The assignee's name — only shown when you've turned off "Assigned to me". Tasks with no assignee display as _Unassigned_.
- An italicized "_N comments_" footer when the task has one or more comments. Tasks with zero comments show no comment indicator.

## How to use it

### Filtering

- **Assigned to me** toggle at the top — default **on**. Flip it off to see the practice's full task list.
- **Status** chips — `OPEN` is selected by default; tap chips to add or remove statuses. If no status chips are selected, all statuses are included.
- **Label** chips — populated from the active task labels configured for your instance. Tap to include; tapping a selected label removes it. A task only needs to match _one_ of the selected labels.

Changing any filter re-fetches the list immediately.

### Inspecting a task

Tap a task card to expand it. The card reveals, on first expansion:

- The full comment thread, oldest first, each with the commenter's name and timestamp.
- A composer for posting a new comment.
- Action buttons (only shown when available to you).

A chevron icon in the card header rotates to indicate the open/closed state. Tap the card header again to collapse.

### Posting a comment

Type into the composer and tap **Post**. Your comment appears at the bottom of the thread immediately as "You · now". The server records the real authored comment shortly after; it will show with your actual name and timestamp on the next refetch.

### Assigning a task to yourself

An **Assign to me** button appears in the detail drawer when the current user isn't already the assignee. Tap it to take ownership. The task list refetches, so the card may move in the list or disappear depending on your filters.

### Marking a task complete

A **Mark complete** button appears in the detail drawer when the task is assigned to you and its status is Open. Tap it to close the task. The server enforces this — if somehow you see the button for a task you don't own, the action returns a 403 and nothing happens.

## Installation

No environment variables or secrets are required.

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/provider_task_dashboard_companion/provider_task_dashboard_companion
```

After install, the plugin registers itself against the `provider_companion_global` scope and will appear in the provider companion launcher on next page load.

Labels surface only if they are **active** and include `"tasks"` in their `modules` list; configure those in your instance's task-label admin.

---

## For developers

### Scope

This plugin uses the `provider_companion_global` `ApplicationScope` — it surfaces on the provider companion main page and does not receive patient or note context.

### Architecture

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

### Endpoints

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

### Known considerations

- **Eventual consistency** — effects are applied asynchronously by the platform, so the `GET /tasks` refetch that runs after "Assign to me" or "Mark complete" may briefly still show the pre-change state. The optimistic UX (append comments client-side; refetch on action) papers over the gap in practice but isn't a strong consistency guarantee.
- **FK filter by UUID** — `Task.assignee_id` targets the integer `dbid` primary key, not the public UUID. The filters here use the double-underscore traversal form (`assignee__id=<uuid>`) to hit the UUID field instead.
- **Staff-only** — all endpoints assume `logged_in_user` is a staff UUID. Patient-side sessions are not supported (nor relevant for a provider companion surface).

## Testing

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/provider_task_dashboard_companion/tests \
    --cov=provider_task_dashboard_companion --cov-branch --cov-report=term-missing
```

Current coverage: **100%** (111 stmts, 14 branches).

## License

MIT. See [LICENSE](./LICENSE).
