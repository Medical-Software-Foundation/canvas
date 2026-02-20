# Clinical & Patient Data Reports

SQL queries for patient demographics, clinical records, medications, lab orders, immunizations, and questionnaire data. These reports support clinical operations, population health analysis, and patient record review.

## Reports

| Report | Description |
|--------|-------------|
| [Active Coverages](active_coverages.md) | Active patients and their current insurance coverage details, including care team lead |
| [Allergies](allergies.md) | Patient allergy and intolerance records with severity, reaction, and FDB Health coding |
| [Completed Prescriptions](completed_prescriptions.md) | Finalized prescriptions with medication name, SIG, quantity, refills, and prescriber |
| [Health Gorilla Codes](healthgorilla_codes.md) | Health Gorilla lab order codes with associated lab names |
| [Immunizations](immunizations.md) | Combined historical (documented) and administered immunizations for active patients |
| [Interview Responses](interview_responses.md) | Completed questionnaire/interview responses with question names and selected values |
| [Lab Test Order Count](labtestorder_count.md) | Frequency count of lab tests ordered, grouped by test name |
| [Medications](medications.md) | Active patient medications with NDC codes, SIG, and FDB Health coding |
| [Patient Conditions](patient_conditions.md) | Active ICD-10 diagnoses for active patients |
| [Patient Demographics](patient_demographics.md) | Patient name, DOB, MRN, birth sex, address, phone, and email |
| [Questionnaire Questions & Responses](questionnaire_questions_responses.md) | Questionnaire configuration — available questions and response options |

## Notes

- Most clinical queries exclude test patients (names containing "zztest" or "test").
- Records marked as deleted or entered-in-error are excluded by default.
- Medication and allergy coding uses the FDB Health system (`http://www.fdbhealth.com/`).
- Each report is available as both a `.sql` file (ready to run) and a `.md` file (documented with column descriptions).
