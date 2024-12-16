-- Retrieves all questionnaires, their associated questions, and response options for analysis.

SELECT
    -- Maps questionnaire status codes to descriptive values
    CASE
        WHEN aq.status = 'AC' THEN 'Active'
        WHEN aq.status = 'IN' THEN 'Inactive'
        ELSE aq.status
    END AS questionnaire_status,
    
    -- Key questionnaire properties
    aq.name AS questionnaire_name,
    aq.use_case_in_charting AS command, -- Linked to charting functionality
    aq.scoring_function_name AS custom_scoring_function,
    aq.code_system AS questionnaire_code_system,
    aq.code AS questionnaire_coding,
    aq.use_in_shx AS questionnaire_used_socialhx, -- Indicates use in social history
    aq.carry_forward AS questionnaire_carryforward, -- Carry-forward capability across visits
    
    -- Associated question details
    q.name AS question_name,
    q.code_system AS question_code_system,
    q.code AS question_code,
    
    -- Response options for each question
    ar.name AS response_name,
    ar.type AS response_type, -- E.g., multiple choice, text
    ar.code_system AS response_code_system,
    ar.code AS response_code
FROM api_questionnaire aq
-- Joins questionnaires to their mapped questions
LEFT JOIN public.api_questionnairequestionmap a ON aq.id = a.questionnaire_id
-- Joins questions to their associated data
LEFT JOIN public.api_question q ON a.question_id = q.id
-- Joins response options to their questions
LEFT JOIN public.api_responseoptionset ar ON q.response_option_set_id = ar.id;
