-- Retrieves appointment information, including associated note details, date of service (DOS), provider, and patient.

SELECT
    -- Appointment details
    apt.id AS apt_UUID,
    an.dbid AS appt_note_id,
    an.datetime_of_service AS appt_note_DOS,
    an.originator_id AS originated_by,
    -- Provider details
    st.first_name || ' ' || st.last_name AS note_provider,
    -- Note details
    an.id as note_external_ID,
    -- Patient details
    ap.first_name || ' ' || ap.last_name as patient_name,
    ap.key AS patient_key
FROM
    canvas_sdk_data_api_appointment_001 apt
LEFT JOIN canvas_sdk_data_api_note_001 an ON apt.note_id = an.dbid
LEFT JOIN canvas_sdk_data_api_staff_001 st ON an.provider_id = st.dbid
LEFT JOIN canvas_sdk_data_api_patient_001 ap ON an.patient_id = ap.dbid
WHERE
    apt.entered_in_error_id IS NULL;
