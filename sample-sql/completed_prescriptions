/*
This query retrieves all prescriptions written in the last week while filtering out:
- Deleted prescriptions
- Uncommitted prescriptions
- Test patient prescriptions
*/

SELECT
    -- Patient details
    ap.mrn AS patient_medrecordnumber,
    ap.key AS patient_key,
    ap.first_name AS patient_first_name,
    ap.last_name AS patient_last_name,
    ap.birth_date AS patient_DOB,

    -- Prescription details
    DATE(rx.written_date) AS written_date,
    am.display AS medication_display,
    rx.sig_original_input AS SIG,
    rx.dispense_quantity AS quantity_to_dispense,
    rx.count_of_refills_allowed AS refills,
    rx.status as erx_status,

    -- Prescriber details
    st.first_name || ' ' || st.last_name AS prescriber_name
FROM
    api_prescription rx
-- Links prescriptions to their associated patients
LEFT JOIN api_patient ap ON rx.patient_id = ap.id
-- Links prescriptions to medication coding details
LEFT JOIN public.api_medicationcoding am ON rx.medication_id = am.medication_id
-- Links prescriptions to their associated medications
LEFT JOIN public.api_medication a ON rx.medication_id = a.id
-- Links prescriptions to prescriber information
LEFT JOIN public.api_staff st ON rx.prescriber_id = st.id
WHERE
    -- Include only committed prescriptions
    rx.committer_id IS NOT NULL
    -- Exclude deleted or erroneous prescriptions
    AND rx.deleted = 'false'
    AND rx.entered_in_error_id IS NULL
    -- Exclude prescriptions for test patients
    AND ap.last_name NOT ILIKE '%test%'
    -- Ensure prescriptions have a valid prescriber
    AND rx.prescriber_id IS NOT NULL
    -- Filter for medications within the FDB Health coding system
    AND am.system = 'http://www.fdbhealth.com/';
