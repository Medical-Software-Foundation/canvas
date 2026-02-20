# Operational & Workflow Reports

SQL queries for appointments, clinical documentation status, and referral tracking. These reports support day-to-day practice operations, documentation compliance, and care coordination.

## Reports

| Report | Description |
|--------|-------------|
| [Appointment Chart Completion](appointment_chart_completion.md) | Each appointment with its note status (signed, unsigned, in progress, no note) plus provider summary |
| [Appointment Volume](appointment_volume.md) | Monthly appointment counts broken out by status (active, cancelled, no-show) |
| [Appointments](apppointments.md) | Appointment details with associated note, provider, and patient information |
| [Appointments by Location](appointments_by_location.md) | Scheduling volume broken down by practice location |
| [Average Wait Time](average_wait_time.md) | Time from scheduled start to encounter start — avg, median, min, max by provider/location |
| [Appointments by Provider](appointments_by_provider.md) | Provider schedule analysis with counts and average duration |
| [Appointments by Type](appointments_by_type.md) | Distribution of visit types (office, video, phone, etc.) |
| [Cancellation Report](cancellation_report.md) | Cancelled appointments with patient, provider, timing, and reason |
| [No-Show Report](no_show_report.md) | No-show rates by provider and location, broken down by month |
| [Notes with Structured RFV](notes_with_structured_rfv.md) | Patient notes with provider and structured reason-for-visit coding |
| [Provider Schedule Availability](provider_schedule_availability.md) | Forward-looking booked vs. free time per provider per day |
| [Referrals](referrals.md) | Referral details including clinical question, priority, and referred-to provider |
| [Time to Next Available](time_to_next_available.md) | Days until next open appointment slot per provider and location |
| [Unlocked Notes](unlocked_notes.md) | Notes with a past date of service that have not yet been signed/locked |

## Notes

- The **Unlocked Notes** report is useful for identifying documentation that still needs provider sign-off.
- Referrals exclude test patients and entries created by Canvas Support.
