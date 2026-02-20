# Cancellation Report

Cancelled appointments with patient, provider, location, timing, and available reason information.

## SQL

```sql
SELECT
    a.id                                AS appointment_id,
    a.externally_exposable_id           AS appointment_uuid,
    p.first_name || ' ' || p.last_name  AS patient_name,
    s.first_name || ' ' || s.last_name  AS provider_name,
    pl.full_name                        AS location_name,
    a.start_time                        AS scheduled_time,
    a.duration_minutes,
    a.comment                           AS appointment_comment,
    ar.display                          AS appointment_reason,
    cancel_event.created                AS cancelled_at
FROM api_appointment a
JOIN api_staff s              ON s.id  = a.provider_id
JOIN api_practicelocation pl  ON pl.id = a.location_id
LEFT JOIN api_patient p       ON p.id  = a.patient_id
LEFT JOIN api_appointmentreason ar
    ON ar.appointment_id = a.id AND ar.user_selected = TRUE
JOIN LATERAL (
    SELECT nse.state, nse.created
    FROM api_notestatechangeevent nse
    WHERE nse.note_id = a.note_id
    ORDER BY nse.created DESC, nse.id DESC
    LIMIT 1
) cancel_event ON cancel_event.state = 'CLD'
WHERE a.entered_in_error_id IS NULL
ORDER BY cancel_event.created DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `appointment_id` | Internal appointment ID |
| `appointment_uuid` | External UUID for the appointment |
| `patient_name` | Patient's full name |
| `provider_name` | Provider's full name |
| `location_name` | Practice location name |
| `scheduled_time` | Originally scheduled appointment time |
| `duration_minutes` | Scheduled appointment duration |
| `appointment_comment` | Free-text comment on the appointment (may contain cancellation reason) |
| `appointment_reason` | User-selected appointment reason, if recorded |
| `cancelled_at` | Timestamp when the cancellation occurred |

## Notes

- Cancellations are identified by the most recent note state being `'CLD'` (Cancelled).
- Canvas does not have a dedicated "cancellation reason" field. The `comment` and `appointment_reason` columns are the closest available data.
