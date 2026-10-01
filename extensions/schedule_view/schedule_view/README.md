schedule_view
=================

## Description

Enriched schedule calendar. Surfaces appointment type,
labels with color coding, provider name, room/location, and appointment
status in a single full-page homepage view — without clicking into each
appointment.

## Features

- **Day / Week / Month views** with appointment cards showing type, provider,
  location, status badge, and label chips
- **Appointment detail modal** — click any card to view details, update status,
  manage labels, or take actions (no-show, cancel)
- **Status updates** — dropdown with all 6 active statuses (Unconfirmed through
  Exited); cancelled/no-show shown as read-only
- **Label management** — add/remove labels (max 3 per appointment, matching
  native Canvas behavior), color-coded chips visible on day and week cards
- **Actions** — No Show (with confirmation) and Cancel (with confirmation)
- **Provider and location filters** — multi-select dropdowns, applied across
  all views including month counts
- **Homepage override** — sets the Schedule View as the default Canvas homepage

## Rescheduling

There is no Reschedule button in the appointment modal. This is intentional.

When used alongside `scheduling_with_rooms` to book appointments with both a
provider and a room, the plugin stashes a room intent in a cache, and the
`RREventOrigination` handler creates a linked room `ScheduleEvent` via
`parent_appointment_id`. Canvas's native reschedule flow does not go through
the plugin's `/book` endpoint, so the room linkage is lost on reschedule —
the old room event is deleted by the cascade, but a new one is never created.

To reschedule a room-coordinated appointment: **cancel** the existing
appointment from the modal, then **book a new one** through the
`scheduling_with_rooms` plugin. This preserves the room linkage.

## Components

| Component | Purpose |
|-----------|---------|
| `applications/schedule_app.py` | Provider menu app — opens the schedule view |
| `handlers/schedule_api.py` | API: HTML shell, appointment JSON, labels, status updates, label management, cancel, no-show |
| `handlers/homepage.py` | Sets Schedule View as default homepage |

## CANVAS_MANIFEST

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure
it gets updated if you add, remove, or rename file or class names.
