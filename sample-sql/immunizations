-- Retrieves a combined list of historical and administered immunizations for active patients,
-- including patient details and immunization metadata.

SELECT
    -- Patient details
    patient_key,
    first_name,
    last_name,
    dob,

    -- Immunization details
    immunization_type,
    code,
    CASE
        WHEN immunization_type = 'Documented (Historical)' THEN 'CPT'
        WHEN immunization_type = 'Administered' THEN 'CVX'
        ELSE NULL
    END AS coding_system,
    display,
    immunization_date,
    lot_number,
    manufacturer,
    expiration_date,
    signature

FROM (
    -- Historical immunizations
    SELECT
        ap.key AS patient_key,
        ap.first_name,
        ap.last_name,
        date(ap.birth_date) AS dob,
        'Documented (Historical)' AS immunization_type,
        a.code,
        a.display,
        ai.date AS immunization_date,
        NULL AS lot_number,
        NULL AS manufacturer,
        NULL AS expiration_date,
        NULL AS signature
    FROM
        api_immunizationstatement ai
    -- Links historical immunizations to their coding details and patients
    LEFT JOIN public.api_immunizationstatementcoding a ON ai.id = a.immunization_statement_id
    LEFT JOIN api_patient ap ON ai.patient_id = ap.id
    WHERE
        -- Exclude deleted or EIE records and include only active patients
        ai.deleted = 'false'
        AND ap.active = 'true'
        AND ai.entered_in_error_id IS NULL

    UNION ALL

    -- Administered immunizations
    SELECT
        ap.key AS patient_key,
        ap.first_name,
        ap.last_name,
        date(ap.birth_date) AS dob,
        'Administered' AS immunization_type,
        ic.code,
        ic.display,
        date(im.created) AS immunization_date,
        im.lot_number,
        im.manufacturer,
        im.exp_date_original AS expiration_date,
        im.sig_original AS signature
    FROM
        api_immunization im
    -- Links administered immunizations to their coding details and patients
    JOIN api_immunizationcoding ic ON im.id = ic.immunization_id
    JOIN api_patient ap ON im.patient_id = ap.id
    WHERE
        -- Include only active patients and valid immunizations
        ap.active = 'true'
        AND im.deleted = 'false'
        AND im.entered_in_error_id IS NULL
) AS combined_immunizations
ORDER BY
    -- Sort by patient key and immunization date in descending order
    patient_key DESC,
    immunization_date DESC;
