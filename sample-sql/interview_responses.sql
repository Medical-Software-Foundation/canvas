-- Retrieves completed interview responses, including patient details, questionnaires, and answers.

SELECT
    -- Interview details
    i.patient_id AS patient_id,
    i.created AS interview_created,
    i.note_id AS interview_note_id,
    
    -- Questionnaire and question details
    q.name AS questionnaire_name,
    qn.name AS question_name,
    
    -- Response details
    iq.response_option_value AS response_value
FROM 
    api_interview i
-- Links interviews to their associated question responses
LEFT JOIN public.api_interviewquestionresponse iq ON i.id = iq.interview_id
-- Links responses to their associated questionnaires
LEFT JOIN public.api_questionnaire q ON iq.questionnaire_id = q.id
-- Links responses to their associated questions
LEFT JOIN public.api_question qn ON iq.question_id = qn.id
-- Links responses to their response options
LEFT JOIN public.api_responseoption ro ON iq.response_option_id = ro.id
WHERE 
    -- Include only completed interviews
    i.committer_id IS NOT NULL
    -- Exclude deleted or erroneous interviews
    AND i.deleted = 'false'
    AND i.entered_in_error_id IS NULL
ORDER BY 
    -- Sort by most recent interview ID
    i.id DESC;
