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

## Sample Output

*Synthetic data for illustration purposes.*

| Month      | Total | Active | Cancelled | No-Shows |
|------------|------:|-------:|----------:|---------:|
| 2026-02-01 |   531 |    475 |        40 |       16 |
| 2026-01-01 |   574 |    508 |        46 |       20 |
| 2025-12-01 |   494 |    442 |        38 |       14 |
| 2025-11-01 |   525 |    465 |        42 |       18 |
| 2025-10-01 |   601 |    525 |        52 |       24 |
| 2025-09-01 |   541 |    488 |        38 |       15 |

### Visualization

![Appointment Volume Chart](assets/appointment_volume_chart.png)

## Tips

- Change `'month'` to `'week'` or `'day'` in `DATE_TRUNC` to adjust time granularity.
- Add a date range filter: `AND a.start_time >= '2024-01-01' AND a.start_time < '2025-01-01'`.
