# Patients by Insurance

Patient counts by insurance plan type, using currently active coverage records.

## SQL

```sql
SELECT
    CASE c.plan_type
        WHEN 'commercial'    THEN 'Commercial'
        WHEN 'medicare'      THEN 'Medicare'
        WHEN 'medicaid'      THEN 'Medicaid'
        WHEN 'bcbs'          THEN 'Blue Cross Blue Shield'
        WHEN 'champus'       THEN 'Tricare/Champus'
        WHEN 'workerscomp'   THEN 'Workers Comp'
        WHEN 'tpa'           THEN 'Third Party Administrator'
        WHEN 'motorvehicle'  THEN 'Motor Vehicle'
        WHEN 'lien'          THEN 'Attorney/Lien'
        WHEN 'pip'           THEN 'Personal Injury'
        WHEN 'other'         THEN 'Other'
        ELSE c.plan_type
    END AS insurance_type,
    COUNT(DISTINCT c.patient_id) AS patient_count
FROM api_coverage c
JOIN api_patient p ON p.id = c.patient_id
WHERE p.active = TRUE
  AND p.under_construction = FALSE
  AND c.state  = 'active'
  AND c.stack  = 'IN_USE'
  AND c.coverage_start_date <= CURRENT_DATE
  AND (c.coverage_end_date IS NULL OR c.coverage_end_date >= CURRENT_DATE)
GROUP BY c.plan_type
ORDER BY patient_count DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `insurance_type` | Human-readable insurance plan type |
| `patient_count` | Number of distinct patients with that coverage type |

## Self-Pay Patients

To identify patients with no active coverage at all, run this separately:

```sql
SELECT
    'Self-Pay (No Active Coverage)' AS insurance_type,
    COUNT(*) AS patient_count
FROM api_patient p
WHERE p.active = TRUE
  AND p.under_construction = FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM api_coverage c
      WHERE c.patient_id = p.id
        AND c.state  = 'active'
        AND c.stack  = 'IN_USE'
        AND c.coverage_start_date <= CURRENT_DATE
        AND (c.coverage_end_date IS NULL OR c.coverage_end_date >= CURRENT_DATE)
  );
```

## Insurance Plan Type Reference

| Code | Display Name |
|------|-------------|
| `commercial` | Commercial |
| `medicare` | Medicare |
| `medicaid` | Medicaid |
| `bcbs` | Blue Cross Blue Shield |
| `champus` | Tricare/Champus |
| `workerscomp` | Workers Comp |
| `tpa` | Third Party Administrator |
| `motorvehicle` | Motor Vehicle |
| `lien` | Attorney/Lien |
| `pip` | Personal Injury |
| `other` | Other |

## Notes

- Active coverage requires `state = 'active'`, `stack = 'IN_USE'`, a start date on or before today, and either no end date or an end date on or after today.
- A patient with multiple active coverages (e.g., primary + secondary) will be counted once per plan type.
