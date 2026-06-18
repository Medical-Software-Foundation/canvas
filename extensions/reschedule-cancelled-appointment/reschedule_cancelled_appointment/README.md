# Reschedule Cancelled Appointment

## What it does

When an appointment is cancelled, this plugin automatically creates a follow-up
**task to reschedule the patient**, so a cancellation never quietly falls
through the cracks. The task is routed to a scheduling team (if one is
configured) or to the appointment's provider, and carries a short summary of the
original appointment.

## Problem it solves

When a patient cancels, someone has to remember to call them back and rebook —
today that depends on a staff member noticing the cancellation and following up
manually. Cancellations get missed, patients go un-booked, and care gaps open
up. This plugin turns every cancellation into an explicit, assigned task so the
rebooking work is always captured and visible.

## Who it's for

Scheduling coordinators and front-desk staff who own rebooking, and the
providers whose cancelled visits need to be filled. It's specialty-agnostic —
any practice that schedules appointments in Canvas.

## How it works

The handler responds to the `APPOINTMENT_CANCELED` event and creates:

- a **task** titled with the provider and the original appointment date/time,
  linked to the patient, due **the next day**; and
- a **comment** summarising the original appointment: reason for visit,
  provider, date/time, location, and note type.

Routing: a **scheduling team** (see `SCHEDULING_TEAM_NAME`) if one matches,
otherwise the **appointment's provider**.

**Labels:** the task inherits the cancelled appointment's active labels, and adds
a `Reschedule` label only if a label of that name already exists in the instance
(it never creates new labels).

**Reason for visit** is read from the appointment note's *Reason For Visit*
command (structured coding and free-text comment combined when both exist),
falling back to the appointment's comment, then `Not documented`.

**Times** are rendered in the instance's configured timezone
(`self.environment["INSTALLATION_TIME_ZONE"]`), falling back to UTC.

The handler does nothing when the appointment can't be found, is marked
entered-in-error, or its start time is missing or already in the past.

## How to install

```
canvas install reschedule-cancelled-appointment
```

Then (optionally) set the `SCHEDULING_TEAM_NAME` secret on the plugin's
configuration page: `<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`.

## Configuration options

| Secret | Required | Description |
|---|---|---|
| `SCHEDULING_TEAM_NAME` | optional | Exact name of the Team that reschedule tasks should be assigned to (matched case-insensitively, e.g. `Scheduling`). If unset/blank or no team matches, tasks are assigned to the appointment's provider. |

No code changes are needed to customise routing — leave `SCHEDULING_TEAM_NAME`
blank to always assign to the provider. The display timezone is taken from the
instance configuration (`INSTALLATION_TIME_ZONE`), not a setting.

## Screenshots

<!-- TODO before publishing: add a screenshot of the generated reschedule task
     (with its summary comment) in a patient's chart, captured from a live
     Canvas instance. -->

## Development

```
uv sync
uv run pytest          # run tests
uv run mypy reschedule_cancelled_appointment
```

## License

MIT — see [LICENSE](../LICENSE).
