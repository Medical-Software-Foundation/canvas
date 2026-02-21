# Clinical & Patient Data Reports

SQL queries for patient demographics, clinical records, medications, lab orders, immunizations, and questionnaire data. These reports support clinical operations, population health analysis, and patient record review.

## Reports

| Report | Description |
|--------|-------------|
| [Active Coverages](active_coverages.md) | Active patients and their current insurance coverage details, including care team lead |
| [Active Patient List](active_patient_list.md) | All active patients with key demographics, default provider, and default location |
| [Allergies](allergies.md) | Patient allergy and intolerance records with severity, reaction, and FDB Health coding |
| [Chronic Disease Registry](chronic_disease_registry.md) | Patients with chronic conditions (diabetes, hypertension, COPD, asthma, heart failure, CKD) by ICD-10 prefix |
| [Completed Prescriptions](completed_prescriptions.md) | Finalized prescriptions with medication name, SIG, quantity, refills, and prescriber |
| [Controlled Substance Report](controlled_substance_report.md) | All controlled substance prescriptions — EPCS coded meds and scheduled compounds |
| [Health Gorilla Codes](healthgorilla_codes.md) | Health Gorilla lab order codes with associated lab names |
| [Immunizations](immunizations.md) | Combined historical (documented) and administered immunizations for active patients |
| [Inactive Patient Report](inactive_patient_report.md) | Active patients who haven't been seen in 6+ months or have never had an appointment |
| [Interview Responses](interview_responses.md) | Completed questionnaire/interview responses with question names and selected values |
| [Lab Test Order Count](labtestorder_count.md) | Frequency count of lab tests ordered, grouped by test name |
| [Medication Changes](medication_changes.md) | Additions, adjustments, sig changes, and discontinuations over the last 30 days |
| [Medications](medications.md) | Active patient medications with NDC codes, SIG, and FDB Health coding |
| [New Patient Report](new_patient_report.md) | New patient registrations grouped by month over the last 12 months |
| [Patient Conditions](patient_conditions.md) | Active ICD-10 diagnoses for active patients |
| [Patients by Diagnosis](patients_by_diagnosis.md) | Patient counts per ICD-10 diagnosis, ranked most to least common |
| [Prescription Status](prescription_status.md) | Prescription counts by e-prescribing status with date ranges |
| [Prescriptions by Drug](prescriptions_by_drug.md) | Medications ranked by prescribing frequency with NDC, avg quantity, and duration |
| [Prescriptions by Drug Class](prescriptions_by_drug_class.md) | Prescriptions grouped by Enhanced Therapeutic Classification (ETC) hierarchy |
| [Prescriptions by Provider](prescriptions_by_provider.md) | Provider prescribing volume, unique patients, refills, adjustments, and EPCS counts |
| [Prescriptions Written](prescriptions_written.md) | Daily prescription counts by date with refill and adjustment breakdowns |
| [Patient Demographics](patient_demographics.md) | Patient name, DOB, MRN, birth sex, address, phone, and email |
| [Patient Demographics Breakdown](patient_demographics_breakdown.md) | Age, sex, race, and ethnicity distribution breakdowns for active patients |
| [Patients by Insurance](patients_by_insurance.md) | Patient counts by insurance plan type (Medicare, Medicaid, Commercial, etc.) |
| [Patients by Location](patients_by_location.md) | Patient distribution across practice locations |
| [Patients by Provider](patients_by_provider.md) | Patient panel size per provider |
| [Questionnaire Questions & Responses](questionnaire_questions_responses.md) | Questionnaire configuration — available questions and response options |
| [Vital Signs by Patient](vital_signs_by_patient.md) | All committed vital sign readings per patient — BP, weight, BMI, height, temperature, pulse, O2 sat, respiration rate |
| [Abnormal Vitals](abnormal_vitals.md) | Patients with out-of-range vitals based on most recent reading and standard clinical thresholds |
| [BMI Distribution](bmi_distribution.md) | Patient population breakdown by WHO BMI categories (underweight through obese class III) |
| [Blood Pressure Control](blood_pressure_control.md) | Most recent BP per patient classified by AHA guidelines with target compliance flag |

## Notes

- Most clinical queries exclude test patients (names containing "zztest" or "test").
- Records marked as deleted or entered-in-error are excluded by default.
- Medication and allergy coding uses the FDB Health system (`http://www.fdbhealth.com/`).
