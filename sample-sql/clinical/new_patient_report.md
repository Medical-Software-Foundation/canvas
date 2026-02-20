# New Patient Report

New patient registrations grouped by month over the last 12 months.

## SQL

```sql
SELECT
    DATE_TRUNC('month', p.created) AS registration_month,
    COUNT(*) AS new_patients
FROM api_patient p
WHERE p.under_construction = FALSE
  AND p.created >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', p.created)
ORDER BY registration_month DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `registration_month` | First day of the month the patients were registered |
| `new_patients` | Number of new patient registrations that month |

## Tips

- Change `'month'` in `DATE_TRUNC` to `'week'` or `'day'` for different granularity.
- For a specific date range instead of a rolling window, replace the `INTERVAL` filter:
  ```sql
  AND p.created >= '2024-01-01'
  AND p.created <  '2025-01-01'
  ```

## Notes

- Includes both active and inactive patients — this shows all registrations regardless of current status.
- Patients still being built in the system are excluded via `under_construction = FALSE`.
