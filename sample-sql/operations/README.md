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
| [Documents by Type](documents_by_type.md) | Document counts broken down by type and category with date ranges |
| [Document Review Status](document_review_status.md) | Reviewed vs. unreviewed counts for each document type |
| [No-Show Report](no_show_report.md) | No-show rates by provider and location, broken down by month |
| [Notes with Structured RFV](notes_with_structured_rfv.md) | Patient notes with provider and structured reason-for-visit coding |
| [Pending Documents](pending_documents.md) | Clinical documents, lab results, imaging, and referral reports awaiting provider review |
| [Pending Referrals](pending_referrals.md) | Outgoing referrals not yet committed, with specialist details and fax status |
| [Provider Schedule Availability](provider_schedule_availability.md) | Forward-looking booked vs. free time per provider per day |
| [Referrals](referrals.md) | Referral details including clinical question, priority, and referred-to provider |
| [Referral Source](referral_source.md) | Outgoing referrals grouped by specialist and specialty with pending/completed counts |
| [Specialist Referral Patterns](specialist_referral_patterns.md) | Which specialists each provider refers to most often |
| [Time to Next Available](time_to_next_available.md) | Days until next open appointment slot per provider and location |
| [Unlocked Notes](unlocked_notes.md) | Notes with a past date of service that have not yet been signed/locked |

## Notes

- The **Unlocked Notes** report is useful for identifying documentation that still needs provider sign-off.
- Referrals exclude test patients and entries created by Canvas Support.
- Canvas does not store a "referral source" field on patients (i.e., where a new patient was referred *from*). The [Referral Source](referral_source.md) report shows outgoing referral patterns instead.
