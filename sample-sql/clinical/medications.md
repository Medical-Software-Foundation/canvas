# Medications

Retrieves active patient medication records, including patient details, medication information, SIG (dosing instructions), and coding metadata.

Pulls SIG from either the prescription or medication statement, whichever is available.

## SQL

```sql
SELECT
    p.key AS patient_key,
    p.first_name AS patient_first_name,
    p.last_name AS patient_last_name,
    p.birth_date,
    mc.display AS med_name,
    m.quantity_qualifier_description,
    COALESCE(rx.sig_original_input, ms.sig_original_input) AS sig_original_input,
    m.status,
    DATE(m.created) AS created_date,
    DATE(m.end_date) AS end_date,
    m.national_drug_code AS representative_ndc,
    mc.code AS fdbhealth_code
FROM
    api_medication m
LEFT JOIN api_medicationcoding mc ON m.id = mc.medication_id
LEFT JOIN api_patient p ON m.patient_id = p.id
LEFT JOIN public.api_prescription rx ON m.id = rx.medication_id
LEFT JOIN public.api_medicationstatement ms ON m.id = ms.medication_id
WHERE
    ms.entered_in_error_id IS NULL
    AND ms.deleted = 'false'
    AND rx.deleted = 'false'
    AND rx.entered_in_error_id IS NULL;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `patient_key` | Unique patient identifier |
| `patient_first_name` | Patient's first name |
| `patient_last_name` | Patient's last name |
| `birth_date` | Patient's date of birth |
| `med_name` | Display name of the medication |
| `quantity_qualifier_description` | Description of the quantity qualifier |
| `sig_original_input` | Dosing instructions (from prescription or medication statement) |
| `status` | Current status of the medication |
| `created_date` | Date the medication record was created |
| `end_date` | End date of the medication (NULL if still active) |
| `representative_ndc` | National Drug Code |
| `fdbhealth_code` | FDB Health medication code |

## Notes

- The SIG field uses `COALESCE` to pull from the prescription first, falling back to the medication statement.
- Excludes deleted and entered-in-error records from both prescriptions and medication statements.
