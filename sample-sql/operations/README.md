# Operational & Workflow Reports

SQL queries for appointments, clinical documentation status, and referral tracking. These reports support day-to-day practice operations, documentation compliance, and care coordination.

## Reports

| Report | Description |
|--------|-------------|
| [Appointments](apppointments.md) | Appointment details with associated note, provider, and patient information |
| [Notes with Structured RFV](notes_with_structured_rfv.md) | Patient notes with provider and structured reason-for-visit coding |
| [Unlocked Notes](unlocked_notes.md) | Notes with a past date of service that have not yet been signed/locked |
| [Referrals](referrals.md) | Referral details including clinical question, priority, and referred-to provider |

## Notes

- The **Unlocked Notes** report is useful for identifying documentation that still needs provider sign-off.
- Referrals exclude test patients and entries created by Canvas Support.
- Each report also has a standalone `.sql` file in the `sample-sql/` root directory for direct use.
