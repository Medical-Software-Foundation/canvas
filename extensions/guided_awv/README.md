# Guided Annual Wellness Visit (AWV) Plugin

A Canvas plugin that provides a structured clinical workflow for Medicare Annual Wellness Visits. It renders as a note-level application tab inside a patient note, guiding providers through all CMS-required AWV elements in an accordion-style UI with integrated clinical scoring, real-time alerts, and direct charting via Canvas SDK commands.

Supports both **Initial AWV (G0438)** and **Subsequent AWV (G0439)** visit types.

## Who It's For

Primary care practices, internal medicine groups, and geriatric practices that perform Medicare Annual Wellness Visits and need a structured workflow for CMS-required documentation and billing.

## Installation

```bash
canvas install guided_awv
```

After installation, configure the AWV note types in your instance so the plugin can auto-detect Initial vs. Subsequent visits. Note types should include `Initial`/`G0438` or `Subsequent`/`G0439` in their name. See the Configuration section for details.

## Use Case

Primary care practices performing Medicare AWV visits need to document a comprehensive set of CMS-required elements - health risk assessment, screening tools, preventive services, medication reconciliation, and more. Without structure, providers risk incomplete documentation, missed screenings, and denied claims.

This plugin walks the provider through every required AWV element in order, auto-scores validated screening instruments, fires clinical alerts for positive screens, and writes structured data directly to the Canvas note via the appropriate SDK commands. The result is a fully documented AWV that meets CMS billing requirements.

| Visit Type | HCPCS Code | Description |
|---|---|---|
| Initial AWV | G0438 | First AWV for the beneficiary (includes all CMS elements) |
| Subsequent AWV | G0439 | Annual follow-up AWV (review & update mode) |

## CMS-Required AWV Elements

The plugin covers all elements required by CMS for AWV billing:

| CMS Element | Plugin Section | Notes |
|---|---|---|
| Health Risk Assessment (HRA) | HRA Module | General health, tobacco, alcohol, exercise, seatbelt, food/housing |
| Medical/surgical history | Medical History Module | Pulls active conditions, surgical history, medications, allergies from ORM |
| Medication reconciliation | Medication Reconciliation Module | Reviews current meds, OTC/supplements, adherence, high-risk meds (Beers Criteria) |
| Family history | Family History Module | Structured per-relative entry with condition checkboxes |
| List of current providers | Current Providers Module | PCP, specialists, pharmacy, DME, home health |
| Vitals (height, weight, BMI, BP) | Vitals Module | Pulls recent LOINC-coded observations; BMI auto-calculated |
| Cognitive assessment | Cognitive Assessment Module | Mini-Cog (default), MoCA, SLUMS, MMSE with auto-scoring |
| Depression screening | Depression Screening Module | PHQ-2 with auto-escalation to PHQ-9 when score >= 3 |
| Functional ability / ADLs | Functional Ability Module | Basic ADL and Instrumental ADL assessment |
| Fall risk assessment | Fall Risk Module | CDC STEADI screening with TUG test and orthostatic BP |
| Hearing & vision screening | Hearing & Vision Module | Subjective + objective assessments |
| Alcohol screening | Alcohol Screening Module | AUDIT-C with sex-specific positive thresholds |
| SDOH screening | SDOH Screening Module | 9 domains: housing, food, transport, safety, isolation, etc. |
| Preventive services checklist | Preventive Services Module | Age/sex-appropriate screenings per USPSTF guidelines |
| Advance care planning | Advance Care Planning Module | ACP discussion, directive types, healthcare proxy |
| Assessment & plan | Assessment & Plan Module | Active conditions, prevention plan, referrals, education |
| Follow-up scheduling | Follow-Up Scheduling Module | Next AWV scheduling and care coordination tasks |

## Workflow Sections (17 Modules)

Each module renders as a collapsible accordion section. Sections are shown or hidden based on visit type (Initial vs. Subsequent). Modules query Canvas ORM for existing patient data and render structured form elements.

| # | Module | ORM Data | Auto-Scoring |
|---|---|---|---|
| 1 | Health Risk Assessment | -- | -- |
| 2 | Medical History | Condition, MedicationStatement, AllergyIntolerance | -- |
| 3 | Medication Reconciliation | MedicationStatement | -- |
| 4 | Family History | -- | -- |
| 5 | Current Providers | -- | -- |
| 6 | Vitals | Observation (LOINC) | BMI auto-calc |
| 7 | Hearing & Vision | -- | -- |
| 8 | Depression Screening | -- | PHQ-2 sum, PHQ-9 sum + severity |
| 9 | Alcohol Screening | -- | AUDIT-C sum + positive flag |
| 10 | Cognitive Assessment | -- | Mini-Cog total + positive screen |
| 11 | SDOH Screening | -- | 9-domain positive detection |
| 12 | Functional Ability | -- | -- |
| 13 | Fall Risk | -- | Orthostatic BP drop, STEADI risk level |
| 14 | Preventive Services | Patient (age, sex) | Age/sex eligibility filtering |
| 15 | Advance Care Planning | -- | -- |
| 16 | Assessment & Plan | Condition | -- |
| 17 | Follow-Up Scheduling | -- | -- |

## Command Capabilities

Each section saves data to the note via the appropriate Canvas SDK command. All API endpoints require staff session authentication (`StaffSessionAuthMixin`).

### Commands by Section

| Section | API Path | Canvas SDK Command | Purpose |
|---|---|---|---|
| Vitals | POST /awv/vitals | `VitalsCommand` | Records height, weight, BP, pulse |
| Depression Screening | POST /awv/depression-screening | `StructuredAssessmentCommand` | PHQ-2 (always) + PHQ-9 (when PHQ-2 >= 3) |
| Cognitive Assessment | POST /awv/cognitive-assessment | `StructuredAssessmentCommand` | Mini-Cog / MoCA / SLUMS / MMSE results |
| Fall Risk | POST /awv/fall-risk | `StructuredAssessmentCommand` | STEADI fall risk assessment |
| Alcohol Screening | POST /awv/alcohol-screening | `StructuredAssessmentCommand` | AUDIT-C results |
| Hearing & Vision | POST /awv/hearing-vision | `StructuredAssessmentCommand` | Hearing and vision screening |
| Functional Ability | POST /awv/functional-ability | `StructuredAssessmentCommand` | ADL/IADL assessment |
| SDOH Screening | POST /awv/sdoh-screening | `StructuredAssessmentCommand` | SDOH 9-domain screening |
| Diagnosis Search | GET /awv/search-conditions | -- (read-only) | ICD-10 autocomplete via ontologies |
| Add Diagnosis | POST /awv/diagnose | `DiagnoseCommand` | Adds ICD-10 diagnosis to note |
| Assessment & Plan | POST /awv/plan | `PlanCommand` + `DiagnoseCommand` + `AddBillingLineItem` | Prevention plan narrative + Z00.00 dx + AWV billing line item |
| Family History | POST /awv/family-history | `FamilyHistoryCommand` | One command per relative |
| Current Providers | POST /awv/current-providers | `TaskCommand` + `CreatePatientPreferredPharmacies` | One task per specialist ("Add [name] ([specialty]) to external care team", unassigned, labels: AWV / Care Team); appends new preferred pharmacies (non-default) without replacing existing ones |
| Pharmacy Search | GET /awv/search-pharmacies | -- (read-only) | Full-text search of Canvas pharmacy directory via `pharmacy_http.search_pharmacies` |
| Preventive Services | POST /awv/preventive-services | `InstructCommand` / `PrescribeCommand` / `LabOrderCommand` / `ImagingOrderCommand` | Discussed/Ordered varies by service type |
| Screening Dates | GET /awv/screening-dates | -- (read-only) | Pre-populates last-done dates from chart history |
| Medication Reconciliation | POST /awv/medication-reconciliation | `ChartSectionReviewCommand` | Marks medications section reviewed |
| Medical History | POST /awv/medical-history | `ChartSectionReviewCommand` | Marks conditions section reviewed |
| Follow-Up | POST /awv/followup | `FollowUpCommand` | Schedules next visit |
| HRA | POST /awv/hra | -- (cache only) | Narrative saved to form state |
| Advance Care Planning | POST /awv/advance-care-planning | -- (cache only) | ACP narrative saved to form state |
| Form State | GET /awv/form-state | -- (read-only) | Retrieves all saved section data |

### Billing-Relevant Codes

**AWV Visit Code (via AddBillingLineItem):**

| Code | Description | Triggered By |
|---|---|---|
| G0438 | Initial AWV | SavePlanHandler (when `awv_cpt_code` = G0438) |
| G0439 | Subsequent AWV | SavePlanHandler (when `awv_cpt_code` = G0439) |
| Z00.00 | Encounter for general adult medical examination | SavePlanHandler (auto-added as diagnosis) |

**CPT Category II Codes (via AddBillingLineItem):**

Quality reporting codes automatically added to the billing footer when sections are saved.

**Diagnosis pointer (Z00.00) on CPT line items:** Each CPT II line item is created with a diagnosis pointer to the Z00.00 ("Encounter for general adult medical examination") Assessment when one is available on the note. The G0438/G0439 AWV visit code uses the same pointer.

Important timing detail: a billing line item can only point at an existing `Assessment`, not at a not-yet-committed `DiagnoseCommand`. Z00.00 is staged as a `DiagnoseCommand` when the provider saves the Assessment & Plan section, and only becomes a real `Assessment` after the user clicks **Commit all commands** at the bottom of the note. As a result:

- Sections saved **before** the user commits will land in the billing footer **without** a diagnosis pointer (expected).
- After committing, re-saving any section backfills the diagnosis pointer on its CPT II line items.

The modal's Provider Attestation section surfaces a "Next steps" banner reminding the user to switch to the Note tab and click Commit all commands.

| Section | CPT II Code | Condition |
|---|---|---|
| Depression Screening | 3725F / 3726F | Positive / Negative screen |
| Cognitive Assessment | 1494F | Dementia cognitive assessment performed |
| Fall Risk | 3288F, 1100F | Fall risk documented, screened for future fall risk |
| Vitals (BMI) | 3008F | BMI documented |
| Vitals (BP - systolic) | 3074F / 3075F / 3077F | SBP <130 / 130-139 / >=140 mmHg (per AMA HEDIS CBP) |
| Vitals (BP - diastolic) | 3078F / 3079F / 3080F | DBP <80 / 80-89 / >=90 mmHg (per AMA HEDIS CBP) |
| HRA (Tobacco) | 1036F | Tobacco use screened |
| Alcohol Screening | 3016F | Unhealthy alcohol use screened |
| Advance Care Planning | 1123F / 1124F | ACP documented / discussed but not completed |
| Functional Ability | 1170F | Functional status assessed |
| Medication Reconciliation | 1111F | Medications reconciled |
| SDOH (Pain) | 1125F / 1126F | Pain present / no pain |

**Screening Questionnaires (via StructuredAssessmentCommand):**

| Questionnaire | Lookup Code | Handler |
|---|---|---|
| PHQ-2 | LOINC `69725-0` | SaveDepressionScreeningHandler |
| PHQ-9 | LOINC `44249-1` | SaveDepressionScreeningHandler |
| AUDIT-C | LOINC `72109-2` | SaveAlcoholScreeningHandler |
| Mini-Cog | Internal `AWV_MINI_COG` | SaveCognitiveAssessmentHandler |
| STEADI Fall Risk | Internal `AWV_STEADI` | SaveFallRiskHandler |
| SDOH Screening | Internal `AWV_SDOH` | SaveSDOHScreeningHandler |
| Hearing & Vision | Internal `AWV_HEARING_VISION` | SaveHearingVisionHandler |
| Functional Ability | Internal `AWV_FUNCTIONAL` | SaveFunctionalAbilityHandler |

**Preventive Services (Discussed → InstructCommand, Ordered → PrescribeCommand / LabOrderCommand / ImagingOrderCommand):**

| Service | CPT Code(s) | Eligibility |
|---|---|---|
| Influenza Vaccine | 90658, 90686 | All patients |
| Pneumococcal Vaccine | 90670, 90732, 90671 | Age >= 65 |
| COVID-19 Vaccine | 91318 | All patients |
| Tdap / Td | 90715, 90714 | Age >= 18 |
| Shingrix (Zoster) | 90750 | Age >= 50 |
| RSV Vaccine | 90679, 90680 | Age >= 60 |
| Colorectal Screening (FIT) | 82274 | Age 45-85 |
| Colorectal Screening (Cologuard) | 81528 | Age 45-85 |
| Colorectal Screening (Colonoscopy) | G0121 | Age 45-85 |
| Mammography | 77067 | Female, age 40-74 |
| DEXA Bone Density | 77080 | Female, age >= 65 |
| Cervical Cancer (Pap/HPV) | 88175, 87624 | Female, age 21-65 |
| Low-Dose CT Lung | 71271 | Age 50-80 |
| Diabetes Screening | 82947, 83036 | All patients |
| AAA Ultrasound | 76706 | Male, age 65-75 |
| PSA (Prostate) | 84153 | Male, age 55-69 |
| Hepatitis C | 86803 | Age 18-79 |
| Lipid Panel | 80061 | All patients |

## Bundled Questionnaires

The plugin registers 5 custom questionnaires for use with `StructuredAssessmentCommand`. These are automatically installed when the plugin is deployed.

| Questionnaire | Code | YAML File |
|---|---|---|
| Mini-Cog Cognitive Assessment | AWV_MINI_COG | questionnaires/mini_cog.yaml |
| STEADI Fall Risk Assessment | AWV_STEADI | questionnaires/steadi_fall_risk.yaml |
| SDOH Screening | AWV_SDOH | questionnaires/sdoh_screening.yaml |
| Hearing and Vision Screening | AWV_HEARING_VISION | questionnaires/hearing_vision.yaml |
| Functional Ability Assessment | AWV_FUNCTIONAL | questionnaires/functional_ability.yaml |

Standard questionnaires (PHQ-2, PHQ-9, AUDIT-C) are expected to already exist in the Canvas instance and are looked up by LOINC code at runtime.

## Screening Date Pre-Population

The Preventive Services section auto-populates "Last done" dates from the patient's chart via `GET /awv/screening-dates`. Data sources:

| Category | Source | Matching Strategy |
|---|---|---|
| Vaccines | `ImmunizationStatement`, `Immunization` | CPT code match + keyword fallback on display text |
| Labs | `LabValueCoding` → `LabValue` → `LabReport` | LOINC code match |
| Imaging | `ImagingOrder` | Keyword match on imaging text field |
| Behavioral Health | `Interview` (questionnaire responses), `Observation`, `Command` | Questionnaire LOINC code, observation LOINC/keyword, command data keyword |
| Session | Plugin cache | Depression/cognitive sections saved in current visit |

Dates older than 1 year for annual screenings display an **(overdue)** badge.

## Cross-Section Pre-Fill

When a section is saved, later sections with overlapping questions are automatically pre-populated:

- **HRA → Functional Ability**: ADL/IADL answers (bathing, dressing, toileting, etc.)
- **HRA → SDOH Screening**: Food security, housing, social support
- **HRA → Alcohol Screening**: Weekly drinks → AUDIT-C frequency
- **Medication Reconciliation → Medical History**: Auto-checks "Medication list reviewed" attestation
- **Depression Screening → Preventive Services**: Auto-fills today's date for Annual Depression Screening
- **Cognitive Assessment → Preventive Services**: Auto-fills today's date for Annual Cognitive Assessment

Pre-filled values are editable. Previously saved section data takes precedence over pre-fill.

## Clinical Alerts

The plugin generates real-time clinical alerts based on screening scores:

| Alert | Trigger | Guidance |
|---|---|---|
| BMI >= 30 | Vitals BMI calculation | CMS requires obesity counseling documentation |
| PHQ-2 positive | PHQ-2 score >= 3 | Auto-expands PHQ-9 for full depression screening |
| PHQ-9 Q9 positive | Suicidal ideation item endorsed | Flags for immediate safety assessment |
| AUDIT-C positive | Score >= 4 (male) or >= 3 (female) | Brief intervention recommended |
| Mini-Cog positive | Score <= 2 | Cognitive impairment; consider referral |
| STEADI high risk | TUG >= 12s or orthostatic drop (SBP >= 20 / DBP >= 10) | Fall intervention recommended |
| SDOH positive domains | Per-domain detection (9 domains) | Domain-specific referral alerts |

## Form State Persistence

Form data is persisted across page loads using a dual-write pattern:

1. **On save**: Raw form field values are cached in the plugin cache keyed by note UUID + section ID
2. **On load**: `GetFormStateHandler` returns all cached section data; the browser restores all field types and re-triggers auto-scoring and conditional visibility
3. **Fallback**: If cache is empty, the handler scans note commands for legacy embedded form state markers

## Configuration

**Requirements:**
- Canvas SDK >= 0.99.1
- Canvas instance with standard PHQ-2/PHQ-9 and AUDIT-C questionnaires (LOINC-coded)
- An AWV note type configured in Canvas admin with **system = `SNOMED`** and **code = `401131001`** (Annual wellness visit). The plugin looks up this exact system+code pair to decide whether to show the Guided AWV button - if the note type is not present, the button does not appear on any note. The note type is system-managed and must be created manually in the Canvas instance settings (it cannot be created from plugin code).

**Initial vs Subsequent AWV:**
There is one AWV note type. The provider selects Initial (G0438) or Subsequent (G0439) via a toggle in the modal header. The choice is persisted per-note in the plugin form-state cache and drives both the AWV billing line item (via `SavePlanHandler`) and section narrative wording.

**Instance-Specific Fallback UUIDs:** The depression screening (PHQ-2, PHQ-9) and alcohol screening (AUDIT-C) handlers look up questionnaire IDs by LOINC code at runtime. If the LOINC lookup fails, they fall back to hardcoded UUIDs that are specific to the development Canvas instance. These fallbacks will not work on other instances. To ensure correct behavior, verify that the target instance has questionnaires with codes `69725-0` (PHQ-2), `44249-1` (PHQ-9), and `72109-2` (AUDIT-C). See `awv_api.py` lines 433, 444, and 1640.

**Secrets:** None required.

**Scope:** `patient_specific` - renders as a tab within individual patient notes.

## Running Tests

```bash
uv run pytest tests/
```

## License

MIT. See [LICENSE](./LICENSE).
