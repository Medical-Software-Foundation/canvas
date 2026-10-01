# Admin staff table (replace dropdown) — Design

**Plugin:** `extensions/external-calendar-busy-blocks`
**Date:** 2026-07-12
**Status:** Approved

## Goal

Replace the admin section's single provider `<select>` + one connect form with a
**table listing every active provider**, one row each, so an admin can attach,
replace, or disconnect a calendar for any provider inline without selecting one
at a time.

## Motivation

During testing, the dropdown forced connecting providers one at a time and made
editing an already-selected provider awkward. A table gives a line-item view of
all providers with per-row actions.

## Design

### Data — `ConfigPage` (server-rendered, one bulk query)

For admins, enrich each active-staff row with its current feed status using a
**single** `StaffCalendarFeed.objects.filter(staff_id__in=[...])` query (no
per-row query — avoids N+1). Each `staff_options` entry becomes:

```
{"id": str, "name": str, "connected": bool,
 "last_sync_at": str | None, "last_error": str | None}
```

`connected` is `True` only when a feed row exists and `is_active`. Nameless and
inactive staff are still excluded (unchanged). Non-admins get `staff_options == []`.

### Template — table

Replace the `<select>` + `#admin-actions` block with a table: columns
**Provider | Status | Secret iCal URL | Actions**. Each `<tr data-staff-id>` has:

- Status cell rendered server-side ("Connected · last sync …" / "Not connected").
- An **empty** `type="url"` input — the stored ICS URL is a bearer token and is
  never returned to the browser; "Replace" means typing a new URL.
- **Connect / Replace** and **Disconnect** buttons; Disconnect is `disabled` when
  the row is not connected.

Widen the page (`max-width`) and add minimal table styling.

### Behavior — per-row JS (event delegation)

One click listener on the table body dispatches by button class and `data-staff-id`:

- **Connect / Replace** → `submitJson(post_url, {ics_url, staff_id})`.
- **Disconnect** → `submitJson(delete_url, {staff_id})`.

After either succeeds, that single row refreshes via the existing
`GET /feeds/status?staff_id=` and updates its status cell + Disconnect enabled
state. Reuses the existing `submitJson` helper; the self-service section and its
MessagePort-safe in-place DOM update are untouched.

### No API / data-model / manifest changes

`POST /feeds`, `POST /feeds/delete`, and `GET /feeds/status` already accept a
target `staff_id` (admin-gated) and already omit the ICS URL from responses. This
change is confined to `ui/pages.py`, `templates/config.html`, and
`tests/ui/test_pages.py`.

## Testing

- `test_pages`: admin `staff_options` carry `connected`/`last_sync_at`/
  `last_error`; a provider with an active feed is `connected: True` with its sync
  time; a provider without a feed is `connected: False`; nameless staff excluded;
  the feed status is resolved with one bulk `staff_id__in` query (not per row);
  non-admin still gets `[]`.
- Template/JS verified by inspection (SDK forbids rendering templates outside
  plugin context; repo has no JS tests) — consistent with prior tasks.

## Out of scope (YAGNI)

Pagination/search for very large staff lists (noted caveat); showing or masking
the stored URL; bulk connect across rows.
