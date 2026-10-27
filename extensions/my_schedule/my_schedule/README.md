my_schedule
===========

## Description

Some practices want each clinician to open Canvas on their own schedule only, so
one provider's patient bookings aren't on show to every other provider. Canvas's
Schedule shows every schedulable provider to everyone. This plugin gives chosen
roles (the ones you list, for example MD, NP and PA) a **My Schedule** page instead:

- At login, restricted staff land on My Schedule: a full-page calendar of **their own**
  visits that looks like Canvas's Schedule. Day and week views are a time grid (white
  where they're available, gray where they're not, a line for the current time); month
  view lists each day's visits. Clicking a visit opens a card with the patient (links to
  the chart), **Open visit note** (where check-in and the video button live), **Join
  video** when the visit has a meeting link, status, reason, location and labels.
- For restricted staff, the built-in **Schedule** menu item and the
  **Appointments** filter in the global panel are hidden.
- When restricted staff book from a patient's chart, the booking window offers
  only themselves as the provider (`BOOK_ONLY_SELF`).
- Everyone else keeps the normal homepage, menu, panel and booking window.

The appointments API always answers for the logged-in staff member, taken from the
session on the server. The page never sends a provider ID, so there's nothing to
change to see someone else's schedule.

## Limits

This changes what restricted staff see by default. **It is not access control.**

- Canvas's `/schedule` page still loads if someone types the address or uses a
  link to it.
- A patient's chart still lists that patient's visits with any provider.
- Staff names still appear elsewhere in Canvas (task assignees, note providers).

Uninstalling returns everyone to the normal Schedule, because Canvas works out
the homepage, menu and panel on each page load.

## Settings

All settings are optional. Blank means the default.

| Setting | Default | What it does |
|---|---|---|
| `RESTRICTED_ROLES` | none | Comma-separated role codes, for example `MD,NP,PA`. Staff with **any** of these roles are restricted. **Blank restricts nobody**, so installing changes nothing until you set it. |
| `EXEMPT_STAFF_IDS` | none | Comma-separated staff IDs that are never restricted, even with a listed role (for example a medical director who manages the schedule). |
| `BOOK_ONLY_SELF` | `yes` | Restricted staff can only pick themselves as the provider in the booking window. Set `no` to leave the list alone. |
| `ALLOW_STATUS_UPDATES` | `no` | Show a status picker on each appointment. |
| `ALLOW_CANCEL` | `no` | Show a Cancel button on each appointment. |
| `ALLOW_NO_SHOW` | `no` | Show a No-show button on each appointment. |
| `GRID_START_HOUR` / `GRID_END_HOUR` | `7` / `19` | Hours the day and week grids show (0-24). The grid widens on its own to fit any visit outside them. |

Actions only ever work on the logged-in staff member's own appointments. A
request for anyone else's appointment gets the same 404 as one that doesn't exist.

## Components

| Component | Purpose |
|---|---|
| `applications/my_schedule_app.py` | Menu app that opens My Schedule full page |
| `handlers/schedule_api.py` | Page, own-appointments JSON, and the optional actions |
| `handlers/homepage.py` | Opens My Schedule at login for restricted staff |
| `handlers/hide_native_schedule.py` | Hides the Schedule menu item and Appointments panel filter for restricted staff |
| `handlers/booking_providers.py` | Limits the booking window's provider list for restricted staff |
| `handlers/access.py` | Who is restricted, from the settings |
| `handlers/availability.py` | The clinician's own availability for shading: calendars titled "<First Last>: Clinic" (open) and "<First Last>: Admin" (blocked), with weekly repeats and exceptions |

## Conflicts

Only one plugin should set the homepage, the provider menu or the global panel on
an instance. Check for `GET_HOMEPAGE_CONFIGURATION`,
`GET_PROVIDER_MENU_CONFIGURATION`, `PANEL_SECTIONS_CONFIGURATION` and
`APPOINTMENT__FORM__PROVIDERS__POST_SEARCH` handlers in other installed plugins
(for example `schedule_view`) before installing.
