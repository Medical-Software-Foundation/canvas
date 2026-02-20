# Patients by Provider

Patient panel size per provider, based on each patient's assigned default provider.

## SQL

```sql
SELECT
    s.id AS provider_id,
    s.first_name || ' ' || s.last_name AS provider_name,
    COUNT(DISTINCT p.id) AS panel_size
FROM api_patient p
JOIN api_staff s ON s.id = p.default_provider_id
WHERE p.active = TRUE
  AND p.under_construction = FALSE
GROUP BY s.id, s.first_name, s.last_name
ORDER BY panel_size DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `provider_id` | Internal staff ID for the provider |
| `provider_name` | Provider's full name |
| `panel_size` | Number of active patients assigned to this provider |

## Including Unassigned Patients

To also show patients with no assigned provider:

```sql
SELECT
    COALESCE(s.first_name || ' ' || s.last_name, '(Unassigned)') AS provider_name,
    COUNT(DISTINCT p.id) AS panel_size
FROM api_patient p
LEFT JOIN api_staff s ON s.id = p.default_provider_id
WHERE p.active = TRUE
  AND p.under_construction = FALSE
GROUP BY s.id, s.first_name, s.last_name
ORDER BY panel_size DESC;
```

## Notes

- Panel size is based on the `default_provider_id` field on the patient record, not on appointment history.
