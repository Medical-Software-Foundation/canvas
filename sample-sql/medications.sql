-- Retrieves active patient medication records, including patient details, medication information, and coding metadata.

SELECT
    -- Patient details
    p.key AS patient_key,
    p.first_name AS patient_first_name,
    p.last_name AS patient_last_name,
    p.birth_date,

    -- Medication details
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
    -- Exclude medication statements and prescriptions entered in error or marked as deleted
    ms.entered_in_error_id IS NULL
    AND ms.deleted = 'false'
    AND rx.deleted = 'false'
    AND rx.entered_in_error_id IS NULL;
