-- Retrieves appointment information, including associated note details, date of service (DOS), provider, and patient.

SELECT
    -- Appointment details
    apt.externally_exposable_id AS apt_UUID,
    an.id AS appt_note_id,
    an.datetime_of_service AS appt_note_DOS,
    an.originator_id AS originated_by,

    -- Provider details
    st.first_name || ' ' || st.last_name AS note_provider,

    -- Note details
    an.externally_exposable_id as note_external_ID,

    -- Patient details
    ap.first_name || ' ' || ap.last_name as patient_name,
    ap.key AS patient_key
FROM
    api_appointment apt
LEFT JOIN public.api_note an ON apt.note_id = an.id
LEFT JOIN public.api_staff st ON an.provider_id = st.id
LEFT JOIN public.api_patient ap ON an.patient_id = ap.id
WHERE
    apt.entered_in_error_id IS NULL;
