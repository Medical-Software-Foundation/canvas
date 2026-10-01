# Admin management of provider calendar feeds — Design

**Plugin:** `extensions/external-calendar-busy-blocks`
**Date:** 2026-07-10
**Status:** Approved

## Goal

Let an authorized admin connect, view, and disconnect a personal calendar feed
**on behalf of any active provider**, so providers don't have to paste their own
secret iCal URL. The existing provider self-service flow is unchanged.

## Background

The plugin today:

- Stores one feed per provider in the `StaffCalendarFeed` custom-data model,
  keyed by `staff_id`.
- Exposes `FeedsAPI` (`POST /feeds`, `POST /feeds/delete`) which always acts on
  the **logged-in** staff, resolved from the `canvas-logged-in-user-id` session
  header via `auth.canonical_staff_id`. A `staff_id` in the request body is
  deliberately ignored today (session is authoritative).
- Renders a self-service modal via `ConfigPage` (`GET /pages/config`) launched
  from the global-scope `BusyBlocksApplication`.
- Runs `SyncCron` every 15 minutes over all active feeds.

## Design

### 1. Authorization — `ADMIN_STAFF_IDS` secret (fail closed)

- New plugin secret `ADMIN_STAFF_IDS`: a comma-separated list of staff UUIDs
  (dashed or dashless accepted).
- New helper `auth.is_admin(staff_id: str | None, secrets: Mapping) -> bool`:
  parses the secret, canonicalizes each entry to dashless form (same
  normalization as `canonical_staff_id`), and returns `True` only when the
  caller's canonical id is in the set.
- Unset / empty / whitespace-only secret → `False` (nobody is admin). This is
  the fail-closed pattern required by `CLAUDE.md`; a missing secret denies
  access, it never grants it.

### 2. UI — one app, admin section (server-rendered)

- `ConfigPage` output is unchanged for regular providers.
- When the logged-in staff `is_admin`, the template additionally renders a
  **"Manage another provider"** section below the self-service form:
  - A `<select>` of **active staff**, server-rendered from
    `Staff.objects.filter(active=True).order_by("last_name", "first_name")`;
    `value` = staff id, label = `full_name`.
  - A status line (populated on selection) plus Connect / Disconnect controls.
- The template context gains `is_admin` and `staff_options`. Non-admins receive
  neither, so the section is never rendered — defense in depth on top of the
  API-level authorization check.

### 3. API — `FeedsAPI` gains a target-staff dimension

- `create_feed` / `delete_feed` read an optional `staff_id` from the JSON body.
  - Target resolution: if `staff_id` is present **and** the caller `is_admin`,
    the target is the canonicalized body `staff_id`; otherwise the target is the
    logged-in staff. A non-admin's body `staff_id` is still ignored (preserves
    today's property and backward compatibility; cannot escalate privilege).
  - All existing validation (HTTPS, whitespace rejection, host allowlist,
    `BEGIN:VCALENDAR` probe) and Admin-calendar provisioning run against the
    **target** staff.
- New route `GET /feeds/status?staff_id=<id>`: **admin-only** (`403` for
  non-admins). Returns JSON `{connected, last_sync_at, last_error}` for the
  selected provider so the dropdown can display live status. It never returns
  the stored ICS URL — the URL is a bearer token and follows the same privacy
  stance as the self-service page.

### 4. Manifest & data access

- Add `ADMIN_STAFF_IDS` to the manifest `secrets` array.
- `FeedsAPI` `data_access.read` gains `"Staff"` (already used transitively by
  `get_admin_calendar_id`).
- `ConfigPage` `data_access.read` gains `"Staff"` (it now lists staff).
- No data-model changes. `StaffCalendarFeed` is already keyed by `staff_id`, so
  an admin-created feed is byte-identical to a self-created one and `SyncCron`
  processes it with no changes.

### 5. Error handling

- Non-admin hitting an admin-only path or targeting another staff: act on self
  (POST) or `403` (status endpoint). Never fail open.
- Admin targeting a non-existent/inactive staff: `get_admin_calendar_id` returns
  `("", [])` when the staff or name cannot be resolved. `create_feed` treats an
  empty calendar id as a failure and returns a clear `400` rather than writing a
  feed row with no calendar to land busy blocks on.
- No broad `try/except` around handler logic. JSON parse failures keep the
  existing `400`.

### 6. Testing

- `auth.is_admin`: unset / empty / whitespace → `False`; dashed and dashless
  membership → `True`; non-member → `False`.
- `FeedsAPI`:
  - Admin connects for another staff → feed keyed to the target, target's Admin
    calendar provisioned.
  - Admin disconnects for another staff → target's imported events deleted.
  - Non-admin's body `staff_id` is ignored (rewrite of the current
    `test_post_ignores_staff_id_in_body`).
  - `GET /feeds/status` returns data for an admin and `403` for a non-admin.
- `ConfigPage`: admin render includes the staff dropdown; non-admin render omits
  it.
- Update `README.md` (new `ADMIN_STAFF_IDS` config row + admin usage notes) and
  bump `plugin_version` in the manifest.

## Out of scope (YAGNI)

- Bulk connect for many providers in one action.
- Editing the `ADMIN_STAFF_IDS` list from the UI.
- An audit log of admin actions.
