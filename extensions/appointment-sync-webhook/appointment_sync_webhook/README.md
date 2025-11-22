# Appointment Sync Webhook

A Canvas plugin that automatically sends webhook notifications when appointments are created, rescheduled, cancelled, or marked as no-show in the Canvas UI. This enables external systems (like custom member portals) to stay synchronized with appointment changes without polling or manual updates.

## Problem Statement

This plugin directly addresses the question posed in [GitHub Discussion #1290](https://github.com/canvas-medical/canvas-plugins/discussions/1290):

> "What is the recommended approach for staying in sync with appointment changes made in Canvas UI?"

When providers or administrators make appointment changes directly in Canvas (creating appointments, cancelling them, or marking patients as no-show), external systems need to be notified to maintain data consistency across platforms.

## Solution

This plugin uses Canvas SDK's event system to listen for appointment lifecycle events and automatically sends HTTP POST notifications to your configured webhook endpoint whenever these events occur.

### Events Handled

- **APPOINTMENT_CREATED**: Triggered when an appointment is first created/booked
- **APPOINTMENT_RESCHEDULED**: Triggered when an appointment is rescheduled within the Canvas UI. The webhook payload includes both the new appointment details and the `original_appointment` object with details of the appointment that was rescheduled.
- **APPOINTMENT_CANCELED**: Triggered when an appointment is cancelled
- **APPOINTMENT_NO_SHOWED**: Triggered when a patient is marked as a no-show

## Installation

1. Install the plugin using the Canvas CLI:
   ```bash
   canvas install /path/to/appointment-sync-webhook
   ```

2. Configure the webhook URL in the Canvas admin panel:
   - Navigate to: `<your-canvas-url>/admin/plugin_io/plugin/`
   - Click the `appointment_sync_webhook` plugin
   - Update the `WEBHOOK_URL` secret to your webhook endpoint URL
   - Save the configuration

## Webhook Payload

When an appointment event occurs, the plugin sends a POST request to your configured webhook URL with the following JSON payload:

```json
{
  "event_type": "appointment_created|appointment_canceled|appointment_no_showed|appointment_rescheduled",
  "appointment": {
    "id": "appointment-uuid",
    "provider_id": "provider-uuid",
    "start_time": "2024-01-15T10:00:00",
    "duration_minutes": 60,
    "end_time": "2024-01-15T11:00:00",
    "original_appointment": {
      "id": "original-appointment-uuid",
      "provider_id": "provider-uuid",
      "start_time": "2024-01-14T10:00:00",
      "duration_minutes": 60,
      "end_time": "2024-01-14T11:00:00"
    }
  },
  "patient": {
    "id": "patient-uuid",
    "first_name": "John",
    "last_name": "Doe"
  },
  "timestamp": "2024-01-15T09:30:00"
}
```

### Payload Fields

- `event_type`: One of `appointment_created`, `appointment_canceled`, `appointment_no_showed`, or `appointment_rescheduled`
  - Note: When an appointment is rescheduled, the event_type is set to `appointment_rescheduled`
- `appointment`: Object containing appointment details
  - `id`: The Canvas appointment UUID
  - `provider_id`: The Canvas provider UUID
  - `start_time`: Appointment start time (ISO 8601 format)
  - `duration_minutes`: Duration of the appointment in minutes
  - `end_time`: Appointment end time (ISO 8601 format, calculated from start_time + duration_minutes)
  - `original_appointment`: Object containing the original appointment details (only present when `event_type` is `appointment_rescheduled`)
    - `id`: The Canvas UUID of the original appointment that was rescheduled
    - `provider_id`: The Canvas provider UUID from the original appointment
    - `start_time`: Original appointment start time (ISO 8601 format)
    - `duration_minutes`: Duration of the original appointment in minutes
    - `end_time`: Original appointment end time (ISO 8601 format, calculated from start_time + duration_minutes)
- `patient`: Object containing patient information (present when the appointment has an associated patient)
  - `id`: The Canvas patient UUID
  - `first_name`: Patient's first name
  - `last_name`: Patient's last name
- `timestamp`: When the event occurred (ISO 8601 format)
