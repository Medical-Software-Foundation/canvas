scheduling-with-rooms
=====================

## Description

Custom scheduling modal that coordinates provider and resource (room)
availability. Patients are booked against a provider's calendar, and when
the visit type requires a room, a corresponding `ScheduleEvent` is created
on the room's calendar in lockstep. Rescheduling or cancelling the patient
appointment cascades to the linked room event automatically.

The Scheduling Admin app exposes a visit-type configuration matrix
(allowed durations, eligible rooms, room-event note types, per-staff
concurrent-slot capacity) persisted under the `scheduling_with_rooms`
Custom Data namespace.

## Components

| Component                                            | Purpose                                                                |
| ---------------------------------------------------- | ---------------------------------------------------------------------- |
| `applications/scheduling_with_rooms_app.py`          | Global menu app — opens the scheduling modal                           |
| `applications/patient_chart_app.py`                  | Patient-chart app — opens the modal pre-filled with the chart patient  |
| `applications/scheduling_admin_app.py`               | Provider-menu admin app for the visit-type/room matrix                 |
| `api/scheduling_api.py`                              | Patient/provider/slot/booking endpoints                                |
| `api/scheduling_admin_api.py`                        | Admin endpoints for visit-type configuration                           |
| `api/calendar.py`, `api/events.py`                   | Provider calendar + availability event endpoints                       |
| `protocols/rfv_origination.py`                       | Originates the RFV command on `APPOINTMENT_CREATED`                    |
| `protocols/appointment_cascade.py`                   | Cascades cancel/reschedule from patient appt → room ScheduleEvent      |
| `handlers/availability_web_app.py`                   | Serves the availability manager UI                                     |
| `models/`                                            | CustomModels: visit-type durations, room mappings, concurrent limits   |
| `utils/fhir_client.py`                               | Minimal FHIR client (uses `FHIR_*` plugin secrets)                     |

## Required secrets

| Secret                    | Purpose                                                            |
| ------------------------- | ------------------------------------------------------------------ |
| `FHIR_BASE_URL`           | Base URL for the Canvas FHIR API                                   |
| `FHIR_CLIENT_ID`          | OAuth2 client id for FHIR access                                   |
| `FHIR_CLIENT_SECRET`      | OAuth2 client secret for FHIR access                               |
| `SCHEDULABLE_STAFF_ROLES` | Comma-separated list of role codes treated as schedulable          |
| `SCHEDULE_DURATIONS`      | Default appointment-duration list (minutes), comma-separated/JSON  |

### FHIR OAuth scopes

When registering the OAuth application that backs `FHIR_CLIENT_ID` /
`FHIR_CLIENT_SECRET`, grant **read-only** access to the resources this plugin
uses — nothing more:

- `Patient.read` — patient timezone lookup for the patient picker
- `Appointment.read` — finding linked room ScheduleEvents during cascade
- `Schedule.read`, `Slot.read` — slot resolution helpers
- `Practitioner.read` — provider lookups for FHIR appointment participants

The plugin does not write via FHIR; do not grant any `*.write` scopes.

### Important Note!

`CANVAS_MANIFEST.json` is used when installing your plugin. Update it if
you add, remove, or rename protocols, applications, or secrets.
