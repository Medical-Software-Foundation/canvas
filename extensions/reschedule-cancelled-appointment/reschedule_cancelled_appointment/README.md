reschedule-cancelled-appointment
================================

## Description

When an appointment is cancelled, this plugin automatically creates a **task to
reschedule the patient** so the follow-up never gets dropped.

The task is routed to:

1. a **scheduling team**, if one is configured (see the `SCHEDULING_TEAM_NAME`
   secret), otherwise
2. the **appointment's provider**.

The task is created with:

- a title naming the provider and the original appointment date/time,
- a link to the patient,
- a due date of **the next day**,
- **labels** inherited from the cancelled appointment, plus a `Reschedule`
  label *only if* a label of that name already exists in the instance (the
  plugin never creates new labels), and
- a **comment** summarising the original appointment: reason for visit,
  provider, date/time, location, and note type.

The reason for visit is read from the appointment note's *Reason For Visit*
command, falling back to the appointment's comment, then `Not documented`.

Times are rendered in the instance's configured timezone
(`self.environment["INSTALLATION_TIME_ZONE"]`), falling back to UTC.

## Behavior

The handler responds to the `APPOINTMENT_CANCELED` event and does nothing
(returns no effects) when:

- the appointment record can't be found,
- the appointment is marked entered-in-error,
- the appointment's start time is missing or already in the past (a cancelled
  past appointment doesn't need rescheduling).

If `SCHEDULING_TEAM_NAME` is set but no team with that name exists, the task
falls back to the appointment's provider (this is a business fallback, not a
security decision).

## Configuration

| Secret | Required | Description |
|---|---|---|
| `SCHEDULING_TEAM_NAME` | optional | Exact name of the Team that reschedule tasks should be assigned to (matched case-insensitively, e.g. `Scheduling`). If unset/blank or no team matches, the task is assigned to the appointment's provider. |

Set secrets on the plugin's configuration page:
`<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`

## Installation

1. Install the plugin into your Canvas instance:
   ```
   canvas install reschedule-cancelled-appointment
   ```
2. (Optional) Set the `SCHEDULING_TEAM_NAME` secret to the name of your
   scheduling team. Leave it blank to always assign reschedule tasks to the
   appointment provider.

## Development

```
uv sync
uv run pytest          # run tests
uv run mypy reschedule_cancelled_appointment
```
