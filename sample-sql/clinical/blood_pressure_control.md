# Blood Pressure Control Report

Patients classified by AHA blood pressure guidelines based on their most recent systolic and diastolic readings from the same visit. Includes a flag indicating whether the patient meets the commonly used < 140/90 mmHg target.

## SQL

```sql
SELECT
    p.id             AS patient_id,
    p.key            AS patient_key,
    p.first_name,
    p.last_name,
    CAST(sys_vs.value AS NUMERIC)  AS systolic,
    CAST(dia_vs.value AS NUMERIC)  AS diastolic,
    sys_vs.date_recorded           AS reading_date,
    CASE
        WHEN CAST(sys_vs.value AS NUMERIC) < 120
         AND CAST(dia_vs.value AS NUMERIC) < 80            THEN 'Normal'
        WHEN CAST(sys_vs.value AS NUMERIC) BETWEEN 120 AND 129
         AND CAST(dia_vs.value AS NUMERIC) < 80            THEN 'Elevated'
        WHEN CAST(sys_vs.value AS NUMERIC) BETWEEN 130 AND 139
          OR CAST(dia_vs.value AS NUMERIC) BETWEEN 80 AND 89 THEN 'Stage 1 Hypertension'
        WHEN CAST(sys_vs.value AS NUMERIC) >= 140
          OR CAST(dia_vs.value AS NUMERIC) >= 90           THEN 'Stage 2 Hypertension'
    END AS bp_category,
    CASE
        WHEN CAST(sys_vs.value AS NUMERIC) < 140
         AND CAST(dia_vs.value AS NUMERIC) < 90            THEN 'Yes'
        ELSE 'No'
    END AS meets_target_140_90
FROM (
    SELECT
        vs.reading_id,
        vs.value,
        vs.date_recorded,
        vsr.patient_id,
        ROW_NUMBER() OVER (PARTITION BY vsr.patient_id ORDER BY vs.date_recorded DESC) AS rn
    FROM api_vitalsign vs
    JOIN api_vitalsignreading vsr ON vs.reading_id = vsr.id
    WHERE vsr.deleted = FALSE
      AND vsr.entered_in_error_id IS NULL
      AND vsr.committer_id IS NOT NULL
      AND vs.sign = 'systole'
      AND vs.value ~ '^\d+\.?\d*'
) sys_vs
JOIN api_vitalsign dia_vs
  ON dia_vs.reading_id = sys_vs.reading_id
 AND dia_vs.sign = 'diastole'
 AND dia_vs.value ~ '^\d+\.?\d*'
JOIN api_patient p ON sys_vs.patient_id = p.id
WHERE sys_vs.rn = 1
ORDER BY p.last_name, p.first_name;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `patient_id` | Internal patient ID |
| `patient_key` | Patient MRN / external key |
| `first_name` | Patient first name |
| `last_name` | Patient last name |
| `systolic` | Most recent systolic BP reading (mmHg) |
| `diastolic` | Most recent diastolic BP reading (mmHg) |
| `reading_date` | Date/time of the BP reading |
| `bp_category` | AHA blood pressure classification |
| `meets_target_140_90` | Whether the patient is below 140/90 mmHg (Yes/No) |

## AHA Blood Pressure Categories

| Category | Systolic | Diastolic |
|----------|----------|-----------|
| Normal | < 120 mmHg | **and** < 80 mmHg |
| Elevated | 120–129 mmHg | **and** < 80 mmHg |
| Stage 1 Hypertension | 130–139 mmHg | **or** 80–89 mmHg |
| Stage 2 Hypertension | ≥ 140 mmHg | **or** ≥ 90 mmHg |

## Notes

- Systolic and diastolic readings are paired from the **same visit/reading** (`reading_id` match) to ensure accurate classification.
- Only each patient's **most recent** BP reading is used.
- The default target is < 140/90 mmHg. Adjust the threshold in the `meets_target_140_90` CASE expression to match your organization's protocols (e.g., < 130/80 for diabetes or CKD patients).
- Non-numeric values are excluded via regex filter.
