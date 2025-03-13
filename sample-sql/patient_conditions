/*
 - Retrieves active patients with their active ICD-10 diagnoses
 - Includes a new line for each condition
*/

SELECT
  ROW_NUMBER() OVER (ORDER BY p.id, c.onset_date) AS "#",
  p.key AS patient_key,
  p.first_name AS "Patient first name",
  p.last_name AS "Patient last name",
  p.birth_date AS "Patient birth date",

  -- Format onset date as YYYY-MM-DD, empty if NULL
  CASE WHEN c.onset_date IS NULL THEN '' ELSE TO_CHAR(c.onset_date, 'YYYY-MM-DD') END AS "onset_date",

  cc.code AS "ICD-10",
  cc.display AS "Diagnosis"

FROM api_patient p
JOIN api_condition c ON c.patient_id = p.id
JOIN api_conditioncoding cc ON cc.condition_id = c.id

WHERE
  p.active = true
  AND c.clinical_status = 'active'
  AND c.deleted = false
  AND c.committer_id IS NOT NULL
  AND c.entered_in_error_id IS NULL
  AND cc.system = 'ICD-10'
  AND p.last_name NOT ILIKE '%zztest%'
  AND p.first_name NOT ILIKE '%zztest%'

ORDER BY p.id ASC, c.onset_date;
