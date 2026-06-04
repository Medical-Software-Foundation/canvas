# External Calendar Busy Blocks — Design Spec

**Date:** 2026-06-01
**Branch:** `external-calendar-busy-blocks`
**Status:** Draft, pending implementation plan

## Problem

Canvas providers maintain personal calendars in Google Calendar, Outlook/O365, or Apple iCloud. When a provider has a dentist appointment, a school pickup, or a vacation block on their personal calendar, schedulers and patients booking through Canvas have no way to know — and double-bookings happen.

Providers want their personal calendar's busy times to appear as blocking events on their Canvas schedule, without exposing the content of those events to Canvas users beyond "Busy."

## Solution overview

A Canvas plugin that lets each provider subscribe Canvas to their personal calendar's secret iCal (ICS) URL. A cron task fetches each feed every 15 minutes, parses busy events, and writes them as Admin (blocking) events on the provider's Canvas calendar. Events removed from the source calendar are removed from Canvas on the next sync.

The ICS subscription approach was chosen over OAuth + FreeBusy polling because:

- ICS works for Google, Outlook, and Apple iCloud with one code path. OAuth requires per-provider integrations (Google, Microsoft); Apple iCloud has no OAuth FreeBusy API at all.
- ICS does not require Canvas Medical to register and maintain OAuth clients or pass Google/Microsoft consent-screen verification.
- ICS does not require token-refresh handling.

Tradeoffs accepted:

- The secret ICS URL is a bearer token. It is stored in plaintext in a plugin-private database table, like other sensitive plugin config. Treated as sensitive; never logged.
- Google's ICS feed is refreshed server-side on a ~30–60 minute lag, so end-to-end sync latency for Google providers is dominated by upstream caching, not by our cron frequency.
- ICS recurrence (`RRULE`) must be expanded plugin-side because the SDK's `Event` effect only supports `DAILY` and `WEEKLY` recurrences with simple `BYDAY` patterns. Real-world calendars use `MONTHLY`, `YEARLY`, and complex `BYDAY` rules that don't survive translation.

## Scope

### In scope (v1)

- Per-provider ICS URL configuration via a global-scope Application.
- Periodic sync (every 15 minutes) that creates/updates/deletes Canvas Admin events to mirror busy times from the source calendar.
- Filtering: only `STATUS=CONFIRMED`, `TRANSP=OPAQUE` events are imported. All-day events that meet those criteria are imported as all-day blocks.
- Reconciliation: events removed from the source calendar are deleted from Canvas, with a safety guard against mass-deletion when feeds return empty unexpectedly.
- A "Reconnect calendar" prompt when an ICS URL becomes invalid (401/403/404).

### Out of scope (v1)

- OAuth flows for Google or Microsoft. ICS is sufficient for v1.
- Tentative events (`STATUS=TENTATIVE`) — skipped.
- Transparent events (`TRANSP=TRANSPARENT`) — skipped.
- Importing event titles or descriptions. Canvas Admin blocks are always titled "Busy".
- Multiple feeds per provider. One feed per staff in v1.
- Admin tooling for bulk feed management (an admin pasting URLs on behalf of providers). Self-service only.
- Cross-staff feed sharing or detection of the same ICS URL across multiple staff.
- At-rest encryption of stored ICS URLs beyond the database's own encryption layer.

## Architecture

Four components, each with a single responsibility:

```
┌─────────────────────────────────┐
│ Application (global scope)      │  Provider-facing config UI.
│ "Calendar Busy Blocks"          │  Renders one of two states:
│                                 │   - Not connected → URL form
│                                 │   - Connected → status + Disconnect
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ SimpleAPIRoute                  │  Form handler. Validates and persists
│ POST /feeds                     │  the URL. Reads staff_id from the
│ DELETE /feeds                   │  authenticated session, never the body.
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ CustomModels (plugin namespace) │  Persistent state.
│  • StaffCalendarFeed            │  One row per provider that connected.
│  • ImportedEvent                │  One row per (ICS UID, recurrence-id)
│                                 │  → Canvas Event id mapping.
└─────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────┐
│ CronTask                        │  The sync engine. The only place that
│ SCHEDULE = "*/15 * * * *"       │  touches the ICS parser or emits
│                                 │  Calendar Event effects.
└─────────────────────────────────┘
```

### Components and dependencies

| Component | Reads | Writes | Effects emitted |
|---|---|---|---|
| `BusyBlocksApplication` | `StaffCalendarFeed` | — | — |
| `FeedsAPI` (`POST /feeds`, `DELETE /feeds`) | `StaffCalendarFeed`, `ImportedEvent` | `StaffCalendarFeed`, `ImportedEvent` | `Event.delete` (on disconnect) |
| `SyncCron` | `StaffCalendarFeed`, `ImportedEvent`, `Calendar` (Admin lookup) | `StaffCalendarFeed`, `ImportedEvent` | `Event.create`, `Event.update`, `Event.delete` |

### SDK dependencies

- `canvas_sdk.handlers.application.Application` — global scope, renders an HTML page
- `canvas_sdk.handlers.simple_api.SimpleAPIRoute` — form handler
- `canvas_sdk.handlers.cron_task.CronTask` — `SCHEDULE = "*/15 * * * *"`
- `canvas_sdk.effects.calendar.Event` — `.create()`, `.update()`, `.delete()`
- `canvas_sdk.v1.data.calendar.Calendar` — `Calendar.objects.for_calendar_name(provider_name=..., calendar_type=CalendarType.Administrative, location=None)`
- `canvas_sdk.v1.data.staff.Staff` — to resolve `provider_name` for the calendar lookup, and to validate `staff_id` on `POST /feeds`
- `canvas_sdk.v1.data.base.CustomModel` — base class for `StaffCalendarFeed` and `ImportedEvent`
- `canvas_sdk.utils.http.Http` — outbound HTTP for ICS feed fetches
- Stdlib (allowlisted): `datetime`, `zoneinfo.ZoneInfo`, `dateutil.relativedelta`, `re`, `urllib.parse`, `arrow.get`

### Sandbox constraint: ICS parsing is hand-rolled

The Canvas plugin runner sandbox (`plugin_runner/sandbox.py` + `plugin_runner/allowed-module-imports.json`) enforces a hard-coded import allowlist. Third-party libraries like `icalendar`, `recurring-ical-events`, and `dateutil.rrule` are NOT allowed, and the allowlist is not extensible per-plugin. The plugin therefore implements its own ICS parser and RRULE expander using only allowlisted modules.

**Supported RRULE subset (covers ~98% of real-world personal calendars):**

- `FREQ=DAILY`, `FREQ=WEEKLY`, `FREQ=MONTHLY`, `FREQ=YEARLY`
- `INTERVAL=N`
- `BYDAY=MO,TU,WE,TH,FR,SA,SU` (and positional variants like `1MO`, `-1FR`)
- `BYMONTHDAY=1,15,-1`
- `BYMONTH=1,6,12`
- `UNTIL=20261231T235959Z`
- `COUNT=N`
- `EXDATE` (excluded instances)
- `RECURRENCE-ID` (instance overrides)

**Explicitly not supported in v1** (drop the VEVENT entirely with a warning log if encountered):

- `BYSETPOS`
- `BYWEEKNO`
- `BYYEARDAY`
- `WKST` other than `MO` (the expander assumes a Monday week start; `WKST=MO` and the omitted default are accepted, a non-`MO` value drops the VEVENT)
- `BYHOUR` / `BYMINUTE` / `BYSECOND`

### Open SDK questions

The MSF-vendored `CANVAS_MANIFEST.json` schema (`canvas_cli/utils/validators/manifest_schema.py`) does not appear to expose a documented field for declaring a plugin's custom-data namespace, despite the SDK's data layer (`canvas_sdk.v1.data.base.CustomModel`, `canvas_sdk.v1.plugin_database_context`) supporting it. Implementation kickoff must confirm with the Canvas SDK team:

1. The manifest declaration syntax (or whether the namespace is inferred from plugin name).
2. The migration/schema-creation mechanism for `CustomModel`s — does the runner create tables automatically, or does the plugin ship migrations?
3. The read/write access-level declaration syntax.

If `CustomModel` support is not available in the deployed SDK version, the fallback is to encode feed URLs in a JSON-blob plugin secret and encode the ICS UID into Canvas Event titles for reconciliation — degraded but functional. This fallback is documented but not preferred.

## Data flow

### A. Provider connects a feed

```
Provider opens "Calendar Busy Blocks" application (global scope)
        │
        ▼
Application reads logged-in staff_id from request context
        │
        ▼
Query StaffCalendarFeed by staff_id
        │
        ├── exists  → render "Connected. Last sync: <ts>. <Disconnect>"
        └── absent  → render "Paste your calendar's secret iCal URL" form
        │
        ▼
Provider submits → POST /plugin-io/api/external_calendar_busy_blocks/feeds
        │
        ▼
FeedsAPI handler:
  1. Read staff_id from session (never from request body)
  2. Validate URL parses as https:// (reject http://, javascript:, file://)
  3. Probe URL with GET; require 2xx and a recognizable text/calendar
     body (begins with "BEGIN:VCALENDAR")
  4. Upsert StaffCalendarFeed(staff_id, ics_url, is_active=True,
     created_at=now, last_etag=null, last_modified=null)
  5. Respond 200 with the updated app HTML (or redirect to GET app)
```

### B. Provider disconnects

```
POST /plugin-io/api/external_calendar_busy_blocks/feeds/delete (or DELETE)
        │
        ▼
FeedsAPI handler:
  1. Read staff_id from session
  2. Look up StaffCalendarFeed; if absent → 200 (idempotent)
  3. For each ImportedEvent for this staff → emit Event.delete effect,
     delete ImportedEvent row
  4. Delete StaffCalendarFeed row
  5. Respond 200
```

### C. Cron sync (every 15 min)

```
SyncCron.execute() fires every quarter hour
        │
        ▼
For each StaffCalendarFeed where is_active=True:
  │
  ├── Look up Admin Calendar via
  │    Calendar.objects.for_calendar_name(
  │      provider_name=staff.full_name,
  │      calendar_type=CalendarType.Administrative,
  │      location=None
  │    ).last()
  │
  │    ├── None  → set last_error="no Admin calendar for this provider",
  │    │           continue to next feed
  │    └── found → continue
  │
  ▼
  Fetch ICS via Http.get(url, headers={
    "If-None-Match": feed.last_etag,
    "If-Modified-Since": feed.last_modified
  }), timeout=30s
  │
  ├── 304 Not Modified  → update last_sync_at, last_error=null, continue
  ├── 200 OK            → continue with body
  ├── 401/403/404       → set is_active=False, last_error=<status>,
  │                       leave ImportedEvents intact, continue
  ├── 5xx / timeout     → set last_error=<status>, leave is_active=True,
  │                       no effects, continue (retry next tick)
  └── Other             → same as 5xx
  │
  ▼
  Parse ICS body with plugin's IcsParser.parse(body):
  │
  ├── Raises IcsParseError → set last_error="parse failure: <type>",
  │                          log first occurrence to Sentry, suppress on
  │                          next ticks for this feed, no effects, continue
  └── Returns               → continue
  │
  ▼
  Filter VEVENTs:
  │
  ├── Drop if STATUS == "CANCELLED"
  ├── Drop if TRANSP == "TRANSPARENT"
  ├── Drop if STATUS == "TENTATIVE"
  ├── Keep CONFIRMED + OPAQUE (default if absent)
  └── Keep all-day events (DTSTART;VALUE=DATE) that meet above
  │
  ▼
  Expand RRULE within [now, now + 90 days]:
  │
  ├── Honor EXDATE exclusions
  ├── Honor RECURRENCE-ID instance overrides
  ├── Convert DTSTART/DTEND to UTC using TZID or VTIMEZONE blocks
  ├── For floating-time events (no TZID), resolve to feed default
  │   timezone (best effort: VCALENDAR X-WR-TIMEZONE)
  └── Cap expansion at 1000 instances per VEVENT; log warning if hit
  │
  ▼
  Yield ParsedEvent(uid, recurrence_id, starts_at_utc, ends_at_utc,
                    is_all_day, sequence)
  │
  ▼
  ─── SAFETY GUARD ──────────────────────────────────────────────
  If parsed_events is empty AND ImportedEvent.count(staff)>0:
    set last_error="feed parsed but empty; deletions skipped",
    skip the diff phase entirely, continue.
  ────────────────────────────────────────────────────────────────
  │
  ▼
  Diff parsed_events against ImportedEvent rows for this staff:
  │
  ├── ParsedEvent (uid, recurrence_id) not in DB:
  │     → Event.create(calendar_id=admin_calendar.id, title="Busy",
  │                    starts_at=..., ends_at=...).create()
  │     → insert ImportedEvent(staff_id, ics_uid, recurrence_id,
  │                            canvas_event_id, last_seen=now,
  │                            sequence, starts_at, ends_at)
  │
  ├── ParsedEvent matches DB row, times/sequence unchanged:
  │     → update last_seen=now on the ImportedEvent row, no effect
  │
  ├── ParsedEvent matches DB row but times or sequence differ:
  │     → Event(event_id=existing.canvas_event_id, title="Busy",
  │             starts_at=..., ends_at=...).update()
  │     → update ImportedEvent row with new times, sequence, last_seen
  │
  └── DB row not in parsed_events:
        → Event(event_id=row.canvas_event_id).delete()
        → delete ImportedEvent row
  │
  ▼
  Update StaffCalendarFeed: last_sync_at=now, last_etag=<response>,
  last_modified=<response>, last_error=null
```

### Lookahead window

`LOOKAHEAD_DAYS` is a plugin secret defaulting to `90`. The `SyncCron` window is `[now, now + LOOKAHEAD_DAYS]`. Events with `ends_at` in the past are not deleted by the cron — they age out naturally on the source calendar. Tunable without code change if 90 turns out to be wrong.

## Data model

### `StaffCalendarFeed`

One row per provider that has connected a feed.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID (auto) | Primary key |
| `staff_id` | CharField(32) | Canvas staff key; unique constraint (one feed per staff) |
| `ics_url` | TextField | The secret ICS URL. Treated as sensitive; never logged. |
| `is_active` | BooleanField | Set false when feed returns 401/403/404 until reconnected |
| `last_sync_at` | DateTimeField, nullable | Most recent successful sync (including 304s) |
| `last_etag` | CharField(256), nullable | From last 200 response; sent as `If-None-Match` |
| `last_modified` | CharField(64), nullable | From last 200 response; sent as `If-Modified-Since` |
| `last_error` | TextField, nullable | Most recent error category for display in UI |
| `created_at` | DateTimeField (auto) | Audit |
| `updated_at` | DateTimeField (auto) | Audit |

### `ImportedEvent`

One row per (ICS UID, recurrence-id) → Canvas Event id mapping.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID (auto) | Primary key |
| `staff_id` | CharField(32) | Canvas staff key, FK-by-value to `StaffCalendarFeed.staff_id` |
| `ics_uid` | CharField(512) | The VEVENT's UID property |
| `recurrence_id` | CharField(64), nullable | RFC 5545 RECURRENCE-ID for individual instances; null for non-recurring or the first instance |
| `canvas_event_id` | CharField(64) | The Canvas Event id we created |
| `sequence` | IntegerField | VEVENT SEQUENCE; bumped by source on updates |
| `starts_at` | DateTimeField | UTC; mirrors what we wrote to Canvas |
| `ends_at` | DateTimeField | UTC; mirrors what we wrote to Canvas |
| `is_all_day` | BooleanField | For display debugging |
| `last_seen` | DateTimeField | Set to `now` whenever we observe this event in a parsed feed; used as a forensic aid |
| `created_at` | DateTimeField (auto) | Audit |

Unique constraint on `(staff_id, ics_uid, recurrence_id)`.

## Error handling

| Scenario | Handling | UI surface |
|---|---|---|
| Invalid/expired ICS URL (401/403/404) | Deactivate feed (`is_active=False`), record `last_error`, leave imported events intact | "Calendar disconnected — please reconnect" with button |
| Transient 5xx / timeout / DNS failure | Record `last_error`, leave feed active, retry next tick, no effects | Subtle "Last sync: 2 hours ago" — silent unless persistent |
| Malformed ICS body | Record `last_error="parse failure: <type>"`, leave events intact, log first occurrence to Sentry then suppress | "Calendar format error — please verify URL" |
| Successful fetch, parses to empty, DB has prior events | Safety guard: skip deletions, record `last_error="feed parsed but empty; deletions skipped"` | Subtle warning; auto-resolves when feed returns non-empty |
| Staff has no Admin Calendar in Canvas | Record `last_error="no Admin calendar"`, skip sync (shouldn't happen — Canvas auto-creates) | Internal Sentry alert |
| RRULE expansion exceeds 1000 instances per VEVENT | Cap at 1000, emit warning log, continue | None — internal only |
| Provider submits a non-HTTPS or non-ICS URL | 400 with error message | Inline form error |
| Provider submits the URL while already connected | Treated as replace: old `StaffCalendarFeed` row updated, `ImportedEvent` rows kept and reconciled on next sync | Status updates to "Connected, syncing" |

### Bearer-token-in-URL

ICS URLs containing secret tokens are sensitive. Mitigations:

- HTTPS-only validation on save (reject http://, file://, javascript:)
- URLs never logged in full. Logs include host and path, with the secret query parameter (`token`, `key`, `secret`, anything `len > 16` matching a hex/base64 pattern) redacted to `***`
- Documented in README so customers understand the risk

Not mitigated in v1:

- At-rest encryption beyond what the database provides natively. Adding a per-plugin KMS-backed encryption layer is disproportionate to the risk (a compromised database already exposes Canvas-wide PHI).

## Observability

- Every `SyncCron.execute()` run emits a structured log: `feed_count`, `success_count`, `not_modified_count`, `failure_count`, `events_created`, `events_updated`, `events_deleted`, `duration_ms`
- Per-feed errors surfaced to the provider via the Application UI's "Last sync" status line
- First occurrence of a parse failure is sent to Sentry; subsequent occurrences for the same feed are suppressed for the day to avoid noise
- The `StaffCalendarFeed.last_error` field is the source of truth for the UI; it's overwritten on each tick

## Security

- The `POST /feeds` endpoint requires an authenticated Canvas session. The `staff_id` is taken from the session, never from the request body — preventing one provider from setting another's feed.
- The `DELETE /feeds` endpoint has the same authentication and same session-staff-only constraint.
- `Calendar.objects.for_calendar_name` is read; we don't create calendars (relies on Canvas auto-creating Admin calendars per staff).
- The plugin has no `data_access` for clinical data; it only reads `Staff` (for the calendar lookup) and writes `Event`.

## Testing strategy

### Parser/expander unit tests

Pure function: `bytes → list[ParsedEvent]`. Fixtures in `tests/fixtures/ics/`.

| Fixture | Asserts |
|---|---|
| `simple_confirmed.ics` | One CONFIRMED OPAQUE event → one ParsedEvent |
| `transparent_event.ics` | TRANSP:TRANSPARENT → skipped |
| `tentative_event.ics` | STATUS:TENTATIVE → skipped |
| `cancelled_event.ics` | STATUS:CANCELLED → skipped |
| `all_day_event.ics` | DTSTART;VALUE=DATE OPAQUE → ParsedEvent with `is_all_day=True` |
| `weekly_recurring.ics` | RRULE:FREQ=WEEKLY → N occurrences within 90-day window |
| `rrule_with_exdate.ics` | EXDATE excludes a specific instance |
| `recurrence_id_override.ics` | RECURRENCE-ID modifies one instance, leaves the rest |
| `multi_timezone.ics` | Events in PST and UTC both convert to UTC datetimes |
| `floating_time.ics` | DTSTART with no TZID resolves via X-WR-TIMEZONE |
| `unbounded_rrule.ics` | No UNTIL/COUNT → expansion stops at 90-day boundary |
| `oversized_rrule.ics` | RRULE that would expand to >1000 → capped, warning logged |
| `malformed.ics` | Bad bytes → raises caught by sync layer |

### Sync engine effect-list assertions

The CronTask's `execute()` returns `list[Effect]`. Tests inject controlled state via fixtures and assert exact effects emitted. Following project convention: never assert `isinstance(result, list)` — assert the specific effects and their payloads.

| Test | Scenario | Expected effects |
|---|---|---|
| `test_new_event_creates` | ICS has event, DB has no ImportedEvent | 1× `CALENDAR__EVENT__CREATE` with title="Busy" |
| `test_unchanged_event_noop` | ICS event matches existing ImportedEvent (same times, same sequence) | 0 effects |
| `test_time_changed_updates` | ICS event UID matches but DTSTART differs | 1× `CALENDAR__EVENT__UPDATE` |
| `test_sequence_bump_updates` | ICS SEQUENCE bumped, times unchanged | 1× `CALENDAR__EVENT__UPDATE` |
| `test_removed_event_deletes` | ImportedEvent exists, ICS no longer has it | 1× `CALENDAR__EVENT__DELETE` |
| `test_cancelled_status_deletes` | ICS event flipped to STATUS:CANCELLED | 1× `CALENDAR__EVENT__DELETE` |
| `test_safety_guard_skips_deletes` | Empty ICS body, DB has 5 ImportedEvents | 0 effects, `last_error` set |
| `test_304_skips_parsing` | HTTP 304 Not Modified | 0 effects, `last_sync_at` updated |
| `test_401_deactivates_feed` | HTTP 401 | 0 effects, `is_active=False`, `last_error` set |
| `test_5xx_leaves_feed_active` | HTTP 503 | 0 effects, `is_active=True`, `last_error` set |
| `test_inactive_feed_skipped` | `is_active=False` | 0 effects, feed not even fetched |
| `test_no_admin_calendar_skipped` | Staff has no Admin Calendar | 0 effects, `last_error="no Admin calendar"` |
| `test_multiple_feeds_independent` | Feed A fails, Feed B succeeds | Effects from B only; A's failure does not abort the cron |
| `test_rrule_expansion_capped` | RRULE expands to >1000 | At most 1000 create effects + warning logged |
| `test_lookahead_window_respected` | RRULE within 90d emits effects; instances beyond 90d ignored | Only in-window effects |

### SimpleAPI handler tests

| Test | Scenario | Expected |
|---|---|---|
| `test_post_creates_feed` | Logged-in staff submits valid HTTPS ICS URL | 200; `StaffCalendarFeed` row created |
| `test_post_replaces_existing` | Staff already has a feed, submits new URL | Old URL replaced, no duplicate row, `ImportedEvents` retained |
| `test_post_rejects_http` | URL has `http://` scheme | 400; no row |
| `test_post_rejects_javascript` | URL has `javascript:` scheme | 400; no row |
| `test_post_rejects_non_ics_body` | URL responds with `<html>` | 400; no row |
| `test_post_rejects_unauthenticated` | No session | 401 |
| `test_post_uses_session_staff` | Request body claims different staff_id | Ignored — feed assigned to session staff |
| `test_delete_removes_feed_and_events` | Connected staff sends delete | Feed gone, all ImportedEvent rows gone, `Event.delete` effects emitted for each |
| `test_delete_idempotent` | Staff with no feed sends delete | 200, no error, no effects |

### Application smoke tests

- Renders without 500 for an unconnected staff (shows form)
- Renders without 500 for a connected staff (shows status + Disconnect)
- Renders `last_sync_at` when present
- Renders `last_error` when present

### Coverage target

- 100% for parser and sync engine modules
- ~80% for SimpleAPI handlers (form-parsing edge cases not exhaustively covered)
- Application UI rendering tested only at the smoke-test level

### Not tested

- Live HTTP calls to Google/Outlook/Apple (mocked via fixtures; integration testing is separate)
- Cron scheduling itself — relies on the Canvas platform
- The `Event` effect's actual database writes — SDK concern, not ours

## Anti-patterns the design avoids

Per `CLAUDE.md`:

- **No all-patient/all-staff batch on `PLUGIN_CREATED` or `PATIENT_UPDATED`.** Sync is cron-driven only.
- **No fail-open on missing secrets.** If `LOOKAHEAD_DAYS` parses badly, fall back to 90 and log.
- **No bare `except Exception` swallowing errors.** Specific exceptions caught at HTTP and parser boundaries; everything else propagates to Sentry.
- **No N+1 queries.** `SyncCron` fetches all active feeds, all `ImportedEvent` rows for those staff, all Admin calendars in bulk before the per-feed loop.
- **No silent corruption.** `staff_id` is read from the session, never from request body; missing session → 401.
- **No mocks pretending to be the database in tests that test the database.** Sync engine tests use the real `CustomModel` ORM against the test DB.

## Open questions to resolve at implementation kickoff

1. Confirm the `CANVAS_MANIFEST.json` syntax for declaring a custom-data namespace with `read_write` access. If unavailable in the MSF-vendored SDK version, decide between (a) upgrading the SDK version, (b) falling back to the JSON-blob-in-secret approach, or (c) using `Staff.state` as scratch space (least preferred).
2. Confirm whether the Canvas plugin runner auto-creates `CustomModel` tables on plugin install, or whether the plugin must ship migrations.
3. Confirm the `Calendar.objects.for_calendar_name(provider_name=staff.full_name, ...)` lookup is the canonical way to find a staff's Admin calendar, or whether there's a more direct relationship via `Staff` we should use instead.
4. Determine the right plugin-secret values to ship with the manifest: `LOOKAHEAD_DAYS` (default `"90"`), and any HTTP timeout/user-agent overrides.

## Sandbox-imposed scope adjustment (2026-06-01 update)

After spec approval, verification of `plugin_runner/sandbox.py` revealed that third-party ICS libraries (`icalendar`, `recurring-ical-events`, `dateutil.rrule`) are not in the plugin import allowlist and the allowlist is not extensible per-plugin. The "SDK dependencies" section and the data-flow parsing step have been updated to reflect a plugin-internal ICS parser. The supported RRULE subset is documented in the "Sandbox constraint" subsection of "Architecture". The test plan accounts for hand-rolled parser coverage. No other behavior changes.
