/*
This query retrieves a list of patients with key details in a structured format. It includes:

- Patient details: Full name, preferred name, date of birth, medical record number, and birth sex.
- Account status: Indicates whether the patient is active or inactive.
- Address: Displays the patient's full address.
- Contact information: Lists home phone, mobile phone, and email in separate columns.
- Excludes test patients with first or last name including zztest
*/

SELECT
    -- Patient information
    CASE
        WHEN ap.active = TRUE THEN 'Active'
        ELSE 'Inactive'
    END AS active_status,
    ap.key AS patient_key,
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.nickname AS preferred_name,
    ap.birth_date AS DOB,
    ap.mrn AS patient_mrn,
    ap.sex_at_birth AS birth_sex,

    -- Address details
    a.use AS address_use,
    a.type AS address_type,
    CONCAT_WS(' ', a.line1, a.line2, a.city || ', ' || a.state_code, a.postal_code) AS patient_address,

    -- Contact details - Aggregated
    MAX(CASE WHEN p.system = 'phone' AND p.use = 'home' THEN p.value END) AS home_phone,
    MAX(CASE WHEN p.system = 'phone' AND p.use = 'mobile' THEN p.value END) AS mobile_phone,
    MAX(CASE WHEN p.system = 'email' THEN p.value END) AS email_address

FROM api_patient ap
-- Links patients to their address records
LEFT JOIN public.api_patientaddress a ON ap.id = a.patient_id
-- Links patients to their contact point records
LEFT JOIN public.api_patientcontactpoint p ON ap.id = p.patient_id

WHERE ap.last_name NOT ILIKE '%zztest%'
AND ap.first_name NOT LIKE '%zztest%'

GROUP BY
    ap.key, ap.first_name, ap.last_name, ap.nickname, ap.birth_date, ap.mrn,
    ap.sex_at_birth, ap.active,
    a.use, a.type, a.line1, a.line2, a.city, a.state_code, a.postal_code;
