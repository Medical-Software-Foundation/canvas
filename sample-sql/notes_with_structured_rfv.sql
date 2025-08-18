-- Purpose: Patient note details with provider and reason-for-visit coding. Most recent first.

-- SELECT: core patient, note, provider, and RFV coding attributes
SELECT
    'https://<instancename>.canvasmedical.com/patient/' || ap.key AS patient_link,
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.birth_date AS patient_dob,
    n.datetime_of_service AS note_dos_utc,
    n.id AS note_id,
    n.externally_exposable_id AS note_uuid,
    st.first_name || ' ' || st.last_name AS note_provider,
    a.system AS rfv_codesystem,
    a.code AS rfv_code,
    a.display AS rfv_display

-- FROM and JOINs: connect notes to patient, provider, RFV, and coding
FROM public.api_note n
LEFT JOIN public.api_reasonforvisit ar ON n.id = ar.note_id
LEFT JOIN public.api_reasonforvisitcoding a ON ar.id = a.reason_for_visit_id
LEFT JOIN public.api_patient ap ON n.patient_id = ap.id
LEFT JOIN public.api_staff st ON n.provider_id = st.id

-- WHERE: add filters as needed (examples)
-- WHERE n.datetime_of_service >= NOW() - INTERVAL '90 days'
--   AND st.id = 123

-- ORDER: newest first
ORDER BY n.datetime_of_service DESC;