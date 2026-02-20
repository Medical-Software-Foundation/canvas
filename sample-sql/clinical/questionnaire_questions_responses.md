# Questionnaire Questions & Response Options

Retrieves all questionnaires, their associated questions, and the available response options.

Useful for understanding what questionnaires are configured in your Canvas instance and what responses are possible.

## SQL

```sql
SELECT
    CASE
        WHEN aq.status = 'AC' THEN 'Active'
        WHEN aq.status = 'IN' THEN 'Inactive'
        ELSE aq.status
    END AS questionnaire_status,
    aq.name AS questionnaire_name,
    aq.use_case_in_charting AS command,
    aq.scoring_function_name AS custom_scoring_function,
    aq.code_system AS questionnaire_code_system,
    aq.code AS questionnaire_coding,
    aq.use_in_shx AS questionnaire_used_socialhx,
    aq.carry_forward AS questionnaire_carryforward,
    q.name AS question_name,
    q.code_system AS question_code_system,
    q.code AS question_code,
    ar.name AS response_name,
    ar.type AS response_type,
    ar.code_system AS response_code_system,
    ar.code AS response_code
FROM api_questionnaire aq
LEFT JOIN public.api_questionnairequestionmap a ON aq.id = a.questionnaire_id
LEFT JOIN public.api_question q ON a.question_id = q.id
LEFT JOIN public.api_responseoptionset ar ON q.response_option_set_id = ar.id;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `questionnaire_status` | "Active" or "Inactive" |
| `questionnaire_name` | Name of the questionnaire |
| `command` | Charting command linked to this questionnaire |
| `custom_scoring_function` | Name of a custom scoring function, if any |
| `questionnaire_code_system` | Code system for the questionnaire |
| `questionnaire_coding` | Code for the questionnaire |
| `questionnaire_used_socialhx` | Whether this questionnaire is used in social history |
| `questionnaire_carryforward` | Whether responses carry forward across visits |
| `question_name` | Name of the question |
| `question_code_system` | Code system for the question |
| `question_code` | Code for the question |
| `response_name` | Name of the response option set |
| `response_type` | Response type (e.g., multiple choice, text) |
| `response_code_system` | Code system for the response |
| `response_code` | Code for the response |

## Notes

- This shows the questionnaire *configuration* (available questions and options), not patient responses. For actual patient responses, see `interview_responses.sql`.
