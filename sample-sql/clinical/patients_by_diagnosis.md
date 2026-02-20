# Patients by Diagnosis (ICD-10 Codes)

Counts how many unique patients have each active ICD-10 diagnosis, ranked from most to least common.

## SQL

```sql
SELECT
    cc.code AS icd10_code,
    cc.display AS diagnosis_description,
    COUNT(DISTINCT c.patient_id) AS patient_count
FROM api_condition c
JOIN api_conditioncoding cc ON cc.condition_id = c.id
WHERE c.clinical_status = 'active'
  AND c.deleted = FALSE
  AND c.entered_in_error_id IS NULL
  AND c.committer_id IS NOT NULL
  AND cc.system = 'ICD-10'
GROUP BY cc.code, cc.display
ORDER BY patient_count DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `icd10_code` | ICD-10 diagnosis code |
| `diagnosis_description` | Display name of the diagnosis |
| `patient_count` | Number of unique patients with this active diagnosis |

## Notes

- Only ICD-10 coded conditions are included (each condition can have multiple coding systems).
- Only active, committed conditions that haven't been entered in error or deleted are counted.
- A patient with the same diagnosis documented multiple times is counted once per ICD-10 code.
