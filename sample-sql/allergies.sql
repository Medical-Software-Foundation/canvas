-- Retrieves allergy records for patients, including status, severity, reaction, and coding information.

SELECT
    -- Allergy details
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
-- Links allergies to their coding information
LEFT JOIN public.api_allergyintolerancecoding a ON aa.id = a.allergy_intolerance_id
-- Links allergies to patient information
LEFT JOIN public.api_patient ap ON aa.patient_id = ap.id
WHERE
    -- Exclude records entered in error or marked as deleted
    aa.entered_in_error_id IS NULL
    AND aa.deleted = 'false'
    -- Filter for FDB Health system codes
    AND a.system = 'http://www.fdbhealth.com/'
ORDER BY 
    -- Sort by patient key in descending order
    ap.key DESC;
