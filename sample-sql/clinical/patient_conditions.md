# Patient Conditions

Retrieves active patients with their active ICD-10 diagnoses. Each condition appears on its own row.

Excludes test patients (names containing "zztest"), deleted conditions, uncommitted conditions, and entered-in-error records.

## SQL

```sql
SELECT
    ROW_NUMBER() OVER (ORDER BY p.id, c.onset_date) AS "#",
    p.key AS patient_key,
    p.first_name AS "Patient first name",
    p.last_name AS "Patient last name",
    p.birth_date AS "Patient birth date",
    CASE WHEN c.onset_date IS NULL THEN '' ELSE TO_CHAR(c.onset_date, 'YYYY-MM-DD') END AS "onset_date",
    cc.code AS "ICD-10",
    cc.display AS "Diagnosis"
FROM api_patient p
JOIN api_condition c ON c.patient_id = p.id
JOIN api_conditioncoding cc ON cc.condition_id = c.id
WHERE
    p.active = true
    AND c.clinical_status = 'active'
    AND c.deleted = false
    AND c.committer_id IS NOT NULL
    AND c.entered_in_error_id IS NULL
    AND cc.system = 'ICD-10'
    AND p.last_name NOT ILIKE '%zztest%'
    AND p.first_name NOT ILIKE '%zztest%'
ORDER BY p.id ASC, c.onset_date;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `#` | Row number |
| `patient_key` | Unique patient identifier |
| `Patient first name` | Patient's first name |
| `Patient last name` | Patient's last name |
| `Patient birth date` | Patient's date of birth |
| `onset_date` | Date the condition started (formatted YYYY-MM-DD, empty if NULL) |
| `ICD-10` | ICD-10 diagnosis code |
| `Diagnosis` | Display name of the diagnosis |

## Notes

- Only ICD-10 coded conditions are included.
- A patient with multiple active conditions will appear on multiple rows.
- Test patients (names containing "zztest") are excluded.
