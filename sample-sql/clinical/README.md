# Clinical & Patient Data Reports

SQL queries for patient demographics, clinical records, medications, lab orders, immunizations, and questionnaire data. These reports support clinical operations, population health analysis, and patient record review.

## Reports

| Report | Description |
|--------|-------------|
| [Active Coverages](active_coverages.md) | Active patients and their current insurance coverage details, including care team lead |
| [Active Patient List](active_patient_list.md) | All active patients with key demographics, default provider, and default location |
| [Allergies](allergies.md) | Patient allergy and intolerance records with severity, reaction, and FDB Health coding |
| [Completed Prescriptions](completed_prescriptions.md) | Finalized prescriptions with medication name, SIG, quantity, refills, and prescriber |
| [Health Gorilla Codes](healthgorilla_codes.md) | Health Gorilla lab order codes with associated lab names |
| [Immunizations](immunizations.md) | Combined historical (documented) and administered immunizations for active patients |
| [Inactive Patient Report](inactive_patient_report.md) | Active patients who haven't been seen in 6+ months or have never had an appointment |
| [Interview Responses](interview_responses.md) | Completed questionnaire/interview responses with question names and selected values |
| [Lab Test Order Count](labtestorder_count.md) | Frequency count of lab tests ordered, grouped by test name |
| [Medications](medications.md) | Active patient medications with NDC codes, SIG, and FDB Health coding |
| [New Patient Report](new_patient_report.md) | New patient registrations grouped by month over the last 12 months |
| [Patient Conditions](patient_conditions.md) | Active ICD-10 diagnoses for active patients |
| [Patient Demographics](patient_demographics.md) | Patient name, DOB, MRN, birth sex, address, phone, and email |
| [Patient Demographics Breakdown](patient_demographics_breakdown.md) | Age, sex, race, and ethnicity distribution breakdowns for active patients |
| [Patients by Insurance](patients_by_insurance.md) | Patient counts by insurance plan type (Medicare, Medicaid, Commercial, etc.) |
| [Patients by Location](patients_by_location.md) | Patient distribution across practice locations |
| [Patients by Provider](patients_by_provider.md) | Patient panel size per provider |
| [Questionnaire Questions & Responses](questionnaire_questions_responses.md) | Questionnaire configuration — available questions and response options |

## Notes

- Most clinical queries exclude test patients (names containing "zztest" or "test").
- Records marked as deleted or entered-in-error are excluded by default.
- Medication and allergy coding uses the FDB Health system (`http://www.fdbhealth.com/`).
