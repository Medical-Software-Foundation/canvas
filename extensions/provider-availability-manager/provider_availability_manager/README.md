provider-availability-manager
=============================

## What it does

A standalone Canvas plugin that lets staff define provider availability
windows in a drag-and-schedule weekly calendar and then **enforces those
windows in Canvas's native appointment book**. Slots that fall outside a
provider's configured Available windows — or that overlap a Busy block —
are removed from the slot list the native scheduler shows.

Front-desk staff continue to use Canvas's native scheduling workflow.
There is no custom booking modal.

The plugin is derived from the Manage Availability tab in
[scheduling-with-rooms](../scheduling-with-rooms/), with all rooms,
visit-type matrix, and custom booking modal code removed.

## Components

| Component                                                  | Purpose                                                                            |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `applications/provider_availability_app.py`                | Provider-menu (hamburger) entry — opens the availability manager UI                |
| `handlers/availability_web_app.py`                         | Serves the drag-and-schedule HTML / JS / CSS                                       |
| `api/calendar.py`                                          | Create or retrieve provider Clinic / Admin calendars                               |
| `api/events.py`                                            | CRUD for the calendar events that express availability                             |
| `protocols/availability_slot_filter.py`                    | Filters `APPOINTMENT__SLOTS__POST_SEARCH` results down to the configured windows   |

## Availability manager UI

Open **Manage Availability** from the three-line / hamburger menu.

| Calendar type           | Effect                                              |
| ----------------------- | --------------------------------------------------- |
| Available (`Clinic`)    | Time is bookable                                    |
| Busy (`Administrative`) | Time is blocked off (breaks, meetings, OOO, etc.)   |

Each event can be one-off or recurring (daily / weekly). Windows can
optionally be tagged with a list of note types via the manager UI; the
selection is stored on the event and surfaced back in the UI, but the
slot filter does not currently consult it (see Known limitations).

## Slot filtering

`AvailabilitySlotFilter` subscribes to `APPOINTMENT__SLOTS__POST_SEARCH`
and returns `APPOINTMENT__SLOTS__POST_SEARCH_RESULTS` with the slot list
trimmed to:

```
(Available windows) − (Busy blocks)
```

The filter is **fail-closed**: if a provider has no Available windows
configured for the requested date, every slot for that provider is
dropped. Configure availability before relying on the native scheduler.

## Configuration

`SCHEDULABLE_STAFF_ROLES` (required) — JSON array or comma-separated
list of staff role internal codes that should appear as bookable
providers in the manager (e.g. `["MD", "NP"]`).

Optional `BRAND_*` secrets re-skin the UI without forking — see
`utils/theming.py` for the supported keys.

## Known limitations

- RRULE support is limited to `DAILY` and `WEEKLY` recurrence; `MONTHLY`
  / `YEARLY` patterns and `EXDATE` exceptions are not honored.
- The slot filter assumes the `APPOINTMENT__SLOTS__POST_SEARCH` payload
  exposes a resolvable location in `selected_values`. When it cannot, the
  filter passes slots through unchanged and emits a warning log.
- **Per-note-type restrictions are not yet enforced by the slot filter.**
  The UI lets you tag each Available window with a list of note types
  and the selection persists on the event, but the filter does not read
  a note type from the slot-search context. A window tagged "well-child
  only" still surfaces for any visit type. The full slot-search event
  shape is undocumented; once we confirm where (and whether) Canvas
  exposes the requested note type in `selected_values`, this can be
  wired in. The on-event log line in `AvailabilitySlotFilter.compute`
  prints `selected_values` verbatim to aid that discovery.
- Appointments that bypass the slot picker (drag-and-drop reschedules,
  API-created appointments) are not validated. The slot filter only
  covers the normal slot-search flow.
