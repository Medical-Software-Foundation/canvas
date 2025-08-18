-- Retrieves referral details, including patient and referred-to provider information, filtering out test patients and erroneous referrals.

SELECT
    -- Referral details
    DATE(ar.date_referred) AS referral_date,
    ar.clinical_question AS clinical_question,
    ar.priority AS referral_priority,
    ar.notes AS referral_notes,
    
    -- Patient details
    ap.mrn AS patient_mrn,
    ap.key AS patient_key,
    ap.first_name || ' ' || ap.last_name AS patient_name,
    
    -- Referred-to provider details
    dis.first_name || ' ' || dis.last_name AS referred_to_name,
    dis.practice_name AS referred_to_practice,
    dis.specialty AS referred_to_speciality
FROM 
    api_referral ar
-- Links referrals to patient details
LEFT JOIN public.api_patient ap ON ar.patient_id = ap.id
-- Links referrals to the referred-to provider details
LEFT JOIN public.data_integration_serviceprovider dis ON ar.service_provider_id = dis.id
WHERE 
    -- Exclude referrals created by Canvas Support
    ar.originator_id != 2
    -- Exclude referrals entered in error
    AND ar.entered_in_error_id IS NULL
    -- Exclude deleted referrals
    AND ar.deleted = 'false'
    -- Include only committed referrals
    AND ar.committer_id IS NOT NULL
    -- Exclude test patients
    AND ap.last_name NOT LIKE '%zztest%'
ORDER BY 
    -- Sort by referral creation date in descending order
    DATE(ar.created) DESC;
