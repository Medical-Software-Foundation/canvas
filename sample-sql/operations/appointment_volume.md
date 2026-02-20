# Appointment Volume Report

Appointment counts by month, broken out by status (active, cancelled, no-show).

## SQL

```sql
SELECT
    DATE_TRUNC('month', a.start_time)            AS month,
    COUNT(*)                                       AS total_appointments,
    COUNT(*) FILTER (WHERE a.status NOT IN ('cancelled', 'noshowed')) AS active_appointments,
    COUNT(*) FILTER (WHERE a.status = 'cancelled') AS cancelled,
    COUNT(*) FILTER (WHERE a.status = 'noshowed')  AS no_shows
FROM api_appointment a
WHERE a.entered_in_error_id IS NULL
GROUP BY DATE_TRUNC('month', a.start_time)
ORDER BY month;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `month` | First day of the month |
| `total_appointments` | Total appointments in that month |
| `active_appointments` | Appointments that were not cancelled or no-showed |
| `cancelled` | Cancelled appointments |
| `no_shows` | No-show appointments |

## Tips

- Change `'month'` to `'week'` or `'day'` in `DATE_TRUNC` to adjust time granularity.
- Add a date range filter: `AND a.start_time >= '2024-01-01' AND a.start_time < '2025-01-01'`.
