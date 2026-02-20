# Appointments by Type

Distribution of visit types (office, telehealth, phone, etc.) and note/visit type names.

## SQL

```sql
SELECT
    CASE a.appointment_type
        WHEN 'office'  THEN 'Office Visit'
        WHEN 'video'   THEN 'Video Visit'
        WHEN 'voice'   THEN 'Telephone Visit'
        WHEN 'home'    THEN 'Home Visit'
        WHEN 'lab'     THEN 'Lab Visit'
        WHEN 'offsite' THEN 'Other Offsite Visit'
        ELSE COALESCE(a.appointment_type, 'Unknown')
    END                                              AS appointment_type_label,
    nt.name                                          AS visit_type_name,
    COUNT(*)                                         AS total_appointments,
    COUNT(*) FILTER (WHERE a.status NOT IN ('cancelled', 'noshowed')) AS active_appointments,
    COUNT(*) FILTER (WHERE a.status = 'cancelled')   AS cancelled,
    COUNT(*) FILTER (WHERE a.status = 'noshowed')    AS no_shows
FROM api_appointment a
JOIN api_notetype nt ON nt.id = a.note_type_id
WHERE a.entered_in_error_id IS NULL
GROUP BY a.appointment_type, nt.name
ORDER BY total_appointments DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `appointment_type_label` | Human-readable appointment medium (Office Visit, Video Visit, etc.) |
| `visit_type_name` | Note type / visit type name configured in Canvas |
| `total_appointments` | Total appointments of this type |
| `active_appointments` | Non-cancelled, non-no-show appointments |
| `cancelled` | Cancelled appointments |
| `no_shows` | No-show appointments |

## Appointment Type Reference

| Code | Label |
|------|-------|
| `office` | Office Visit |
| `video` | Video Visit |
| `voice` | Telephone Visit |
| `home` | Home Visit |
| `lab` | Lab Visit |
| `offsite` | Other Offsite Visit |
