# Allergies

Retrieves allergy records for patients, including status, severity, reaction, and coding information.

Filters for FDB Health coding system records and excludes any entries that were entered in error or deleted.

## SQL

```sql
SELECT
    aa.recorded_date AS allergy_recordeddate,
    CASE
        WHEN aa.allergy_intolerance_type = 'A' THEN 'Allergy'
        WHEN aa.allergy_intolerance_type = 'I' THEN 'Intolerance'
        ELSE 'Unknown'
    END AS allergy_type,
    a.display AS allergy,
    aa.severity AS allergy_severity,
    aa.narrative AS allergy_reaction,
    a.system AS allergy_codesystem,
    aa.category || '-' || a.code AS fdb_code
FROM
    api_allergyintolerance aa
LEFT JOIN public.api_allergyintolerancecoding a ON aa.id = a.allergy_intolerance_id
LEFT JOIN public.api_patient ap ON aa.patient_id = ap.id
WHERE
    aa.entered_in_error_id IS NULL
    AND aa.deleted = 'false'
    AND a.system = 'http://www.fdbhealth.com/'
ORDER BY
    ap.key DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `allergy_recordeddate` | Date the allergy was recorded |
| `allergy_type` | "Allergy" or "Intolerance" based on type code |
| `allergy` | Display name of the allergen |
| `allergy_severity` | Severity of the allergy |
| `allergy_reaction` | Narrative description of the reaction |
| `allergy_codesystem` | Code system used (FDB Health) |
| `fdb_code` | Combined category and FDB Health code |

## Notes

- Only records coded in the FDB Health system (`http://www.fdbhealth.com/`) are included.
- The `allergy_type` field maps internal codes: `A` = Allergy, `I` = Intolerance.
