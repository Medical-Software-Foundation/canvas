# Chronic Disease Registry

Identifies patients with specific chronic conditions using ICD-10 code prefixes. Covers diabetes, hypertension, COPD, asthma, heart failure, and chronic kidney disease.

## Patient Detail

```sql
SELECT
    CASE
        WHEN cc.code LIKE 'E11%' THEN 'Type 2 Diabetes'
        WHEN cc.code LIKE 'E10%' THEN 'Type 1 Diabetes'
        WHEN cc.code LIKE 'I10%' OR cc.code LIKE 'I11%' OR cc.code LIKE 'I12%' OR cc.code LIKE 'I13%' THEN 'Hypertension'
        WHEN cc.code LIKE 'J44%' THEN 'COPD'
        WHEN cc.code LIKE 'J45%' THEN 'Asthma'
        WHEN cc.code LIKE 'I50%' THEN 'Heart Failure'
        WHEN cc.code LIKE 'N18%' THEN 'Chronic Kidney Disease'
    END AS chronic_condition,
    p.id AS patient_id,
    p.first_name,
    p.last_name,
    p.birth_date,
    cc.code AS icd10_code,
    cc.display AS diagnosis_description,
    c.onset_date,
    c.clinical_status
FROM api_condition c
JOIN api_conditioncoding cc ON cc.condition_id = c.id
JOIN api_patient p ON p.id = c.patient_id
WHERE c.clinical_status IN ('active', 'relapse', 'remission')
  AND c.deleted = FALSE
  AND c.entered_in_error_id IS NULL
  AND c.committer_id IS NOT NULL
  AND cc.system = 'ICD-10'
  AND (
      cc.code LIKE 'E10%'   -- Type 1 Diabetes
   OR cc.code LIKE 'E11%'   -- Type 2 Diabetes
   OR cc.code LIKE 'I10%'   -- Essential Hypertension
   OR cc.code LIKE 'I11%'   -- Hypertensive heart disease
   OR cc.code LIKE 'I12%'   -- Hypertensive CKD
   OR cc.code LIKE 'I13%'   -- Hypertensive heart + CKD
   OR cc.code LIKE 'J44%'   -- COPD
   OR cc.code LIKE 'J45%'   -- Asthma
   OR cc.code LIKE 'I50%'   -- Heart Failure
   OR cc.code LIKE 'N18%'   -- Chronic Kidney Disease
  )
ORDER BY chronic_condition, p.last_name, p.first_name;
```

| Column | Description |
|--------|-------------|
| `chronic_condition` | Disease category (e.g., "Type 2 Diabetes", "Hypertension") |
| `patient_id` | Internal patient identifier |
| `first_name` | Patient's first name |
| `last_name` | Patient's last name |
| `birth_date` | Date of birth |
| `icd10_code` | Specific ICD-10 code |
| `diagnosis_description` | Display name of the diagnosis |
| `onset_date` | Date the condition started |
| `clinical_status` | Current status (active, relapse, or remission) |

## Summary Count

For a high-level view of how many patients fall into each chronic disease category:

```sql
SELECT
    CASE
        WHEN cc.code LIKE 'E11%' THEN 'Type 2 Diabetes'
        WHEN cc.code LIKE 'E10%' THEN 'Type 1 Diabetes'
        WHEN cc.code LIKE 'I10%' OR cc.code LIKE 'I11%' OR cc.code LIKE 'I12%' OR cc.code LIKE 'I13%' THEN 'Hypertension'
        WHEN cc.code LIKE 'J44%' THEN 'COPD'
        WHEN cc.code LIKE 'J45%' THEN 'Asthma'
        WHEN cc.code LIKE 'I50%' THEN 'Heart Failure'
        WHEN cc.code LIKE 'N18%' THEN 'Chronic Kidney Disease'
    END AS chronic_condition,
    COUNT(DISTINCT c.patient_id) AS patient_count
FROM api_condition c
JOIN api_conditioncoding cc ON cc.condition_id = c.id
WHERE c.clinical_status IN ('active', 'relapse', 'remission')
  AND c.deleted = FALSE
  AND c.entered_in_error_id IS NULL
  AND c.committer_id IS NOT NULL
  AND cc.system = 'ICD-10'
  AND (
      cc.code LIKE 'E10%'
   OR cc.code LIKE 'E11%'
   OR cc.code LIKE 'I10%'
   OR cc.code LIKE 'I11%'
   OR cc.code LIKE 'I12%'
   OR cc.code LIKE 'I13%'
   OR cc.code LIKE 'J44%'
   OR cc.code LIKE 'J45%'
   OR cc.code LIKE 'I50%'
   OR cc.code LIKE 'N18%'
  )
GROUP BY chronic_condition
ORDER BY patient_count DESC;
```

| Column | Description |
|--------|-------------|
| `chronic_condition` | Disease category |
| `patient_count` | Number of unique patients with that condition |

## ICD-10 Code Prefixes Used

| Prefix | Condition |
|--------|-----------|
| `E10%` | Type 1 Diabetes |
| `E11%` | Type 2 Diabetes |
| `I10%` | Essential Hypertension |
| `I11%` | Hypertensive heart disease |
| `I12%` | Hypertensive CKD |
| `I13%` | Hypertensive heart + CKD |
| `J44%` | COPD |
| `J45%` | Asthma |
| `I50%` | Heart Failure |
| `N18%` | Chronic Kidney Disease |

## Tips

- To add more conditions, add ICD-10 prefixes to both the `CASE` statement and the `WHERE` clause (e.g., `cc.code LIKE 'E78%'` for hyperlipidemia).
- Includes conditions that are active, in relapse, or in remission — chronic conditions may cycle through these statuses.
