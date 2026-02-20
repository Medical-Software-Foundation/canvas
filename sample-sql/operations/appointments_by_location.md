# Appointments by Location

Scheduling volume broken down by practice location.

## SQL

```sql
SELECT
    pl.id                                            AS location_id,
    pl.full_name                                     AS location_name,
    COUNT(*)                                         AS total_appointments,
    COUNT(*) FILTER (WHERE a.status NOT IN ('cancelled', 'noshowed')) AS active_appointments,
    COUNT(*) FILTER (WHERE a.status = 'cancelled')   AS cancelled,
    COUNT(*) FILTER (WHERE a.status = 'noshowed')    AS no_shows
FROM api_appointment a
JOIN api_practicelocation pl ON pl.id = a.location_id
WHERE a.entered_in_error_id IS NULL
GROUP BY pl.id, pl.full_name
ORDER BY total_appointments DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `location_id` | Internal practice location ID |
| `location_name` | Full name of the practice location |
| `total_appointments` | Total appointments at this location |
| `active_appointments` | Non-cancelled, non-no-show appointments |
| `cancelled` | Cancelled appointments |
| `no_shows` | No-show appointments |
