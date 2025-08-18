# 🏥 Data Migrations for Canvas

> **Professional tools for migrating Electronic Health Record (EHR) data from any EMR into the Canvas platform**

---

This module contains tools for migrating Electronic Health Record (EHR) data from one EMR into the Canvas platform. It includes data preprocessing, transformation, and structured mapping logic for clinical and administrative data types.

---

## 📑 **Table of Contents**

### 📚 **Core Concepts**
- [What This README Documents](#what-this-readme-documents)
- [Highlights](#highlights)
- [Project Structure](#project-structure)
- [PHI Considerations](#phi-considerations)
- [Common Workflow](#common-workflow)

### 🚀 **Getting Started**
- [Setup](#setup)
- [Plugin Setup](#plugin-setup)
- [Configuration](#configuration)
- [Getting Started](#getting-started)

### 📊 **Data Migration Types**
- [Data Type Specific Details](#data-type-specific-details)
- [Patient Migration](#patient-migration)
- [Command Type Migrations](#command-type-migrations)
- [Allergy Migration](#allergy-migration)
- [Condition Migration](#condition-migration)
- [Medication Migration](#medication-migration)
- [Immunization Migration](#immunization-migration)
- [Family History Migration](#family-history-migration)
- [Appointment Migration](#appointment-migration)
- [Coverage Migration](#coverage-migration)
- [Document Migration](#document-migration)
- [Lab Report Migration](#lab-report-migration)
- [Vitals Migration](#vitals-migration)
- [Message Migration](#message-migration)
- [Consent Migration](#consent-migration)
- [HPI Migration](#hpi-migration)
- [Questionnaire Response Migration](#questionnaire-response-migration)

### 🛠️ **Technical Details**
- [Console Output During Migration](#console-output-during-migration)
- [Result CSV Files](#result-csv-files)
- [Common Validation Patterns](#common-validation-patterns)
- [Mapping](#mapping)
- [Plugins](#plugins)
- [Best Practices](#best-practices)

---

## 📋 What This README Documents

This README provides **comprehensive documentation** for migrating healthcare data from any Medical Record (EMR) systems into Canvas. It serves as a complete reference guide for developers and data engineers performing EMR-to-Canvas data migrations.

### 🎯 Key Areas Covered:

| Area | Description | 📚 Coverage |
|------|-------------|-------------|
| 🔄 **Migration Scripts Overview** | Complete list of all available migration scripts for different data types (patients, allergies, conditions, medications, etc.) | 100% |
| ✅ **Field Requirements & Validation Rules** | Detailed specifications for each data type including required vs. optional fields, data format requirements, validation rules and constraints, mapping requirements | 100% |
| 📊 **Data Format Standards** | Specific requirements for date/time formats, enum values, required field validation, file/document handling | 100% |
| 🗂️ **Mapping File Documentation** | Complete reference for required mapping files, optional mapping files for specific data types, purpose and structure of each mapping file | 100% |
| ⚠️ **Error Handling & Best Practices** | Guidelines for handling failed migrations, tracking progress and results, testing and validation strategies, maintaining data quality during migration | 100% |
| 💻 **Implementation Examples** | Practical guidance for setting up migration environments, configuring mapping files, running migration scripts, troubleshooting common issues | 100% |

This documentation is designed to be the **single source of truth** for anyone performing vendor EMR migrations to Canvas, ensuring consistency, data quality, and successful data transfers.

---

## ✨ Highlights

- 🔄 **Reusable framework**: `data_migrations/template_migration` provides validation and load mixins for common CSV templates (patients, appointments, meds, immunizations, etc.)
- 🏢 **Vendor adapters**: Each subfolder under `data_migrations/` houses scripts tailored to a specific source EMR and its data shape
- 📈 **Deterministic flow**: Most scripts follow a Make CSV → Validate → Load Via API pattern, generating auditable output files under `results/`

---

## 📁 Project Structure

```
data-migrations/
├── 📄 README.md
├── 🔒 poetry.lock
├── ⚙️ pyproject.toml
└── 📦 data_migrations/
    ├── 🛠️ utils.py
    └── 🏢 <vendor>_migration/
        ├── 🔄 create_*.py                     ← Migration scripts for each data type (allergies, vitals, patients, etc.)
        ├── 🗂️ mappings/                       ← JSON mapping files
        ├── 📊 results/                        ← Processed result logs for audit trail (CSV)
        ├── 🔐 PHI/                            ← PHI-specific handling (never commit these to github)
        └── 📝 update_data_migration_notes.py  ← Script to handle locking notes at end of migration
    └── 🧩 template_migration/
        ├── 🔧 *.py               ← Parent mixin migration scripts (allergies, vitals, patients, etc.)
        ├── 🛠️ utils.py           ← Helper functions for validating and loading data
        └── 🗂️ mappings/          ← JSON & CSV mapping files
    └── 🔌 plugins/               ← Canvas Plugins you can install to assist in Data Migration
```

---

## � PHI Considerations 

The `PHI/` submodule exists to house any logic related to **Protected Health Information**. Use this module when handling sensitive data transformations. Keep them out of version control and handle per your security policies.

---

## ⚙️ Setup 

This project uses [Poetry](https://python-poetry.org/) for dependency management.

### 1. 📦 Install Poetry (if not installed)

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### 2. 🐍 Activate virtual environment

```bash
poetry shell
```

### 3. 🔧 Install dependencies

```bash
poetry install
```

---

## 🔌 Plugin Setup 

If you want to take advantage of any plugins in the `plugin` folder, you will need to follow setup instructions to use the Canvas CLI here: [Canvas CLI Documentation](https://docs.canvasmedical.com/sdk/canvas_cli/)

> 💡 **Note**: The Canvas CLI uses a similar pattern to the config.ini mentioned below, but will need to be in a specific location on your computer.

---

## ⚙️ Configuration 

Scripts load credentials and settings from `config.ini` at the root of this folder. Fill in values per environment.

### 🔑 Minimum Keys Used Across Migrations:

#### **Canvas FHIR Auth** (used by `data_migrations/utils.py → FHIRHelper`)
- `client_id`, `client_secret`, `url`
- [Setup Guide](https://docs.canvasmedical.com/api/customer-authentication/)

#### **Vendor-Specific Keys** (example: Avon)
- `avon_client_id`, `avon_client_secret`, `avon_user_id`, `avon_base_subdomain`

### **Canvas SDK Auth** (used by plugins)
- `simple-api-key`

Define one section per target instance. Example sections: `[phi-instance-test]`, etc. Reference the section name in each script's `environment` parameter.

### 📋 Instance Configuration 

To be able to start the data migration, there needs be some initial set up in the instance's settings page. You will work with your implementation manager to make sure these things are setup.

Examples of settings to configure:

| Setting | Description | Example |
|---------|-------------|---------|
| 👥 **Staff** | Staff members and providers | Doctors, nurses, administrators |
| 🏥 **Insurers** | Insurance companies for coverages | Insurers and their addresses and phone numbers |
| 📝 **Note Types** | Canvas Note Types | Historical Data Migration, Vital Import, Future Appointment Types |
| 🎯 **Structured Reason For Visit** | Appointment reason codes | For appointments |
| ✅ **Consent Codings** | Consent type classifications | For consents ingestion |
| 📋 **Questionnaires** | Questionnaires | For question and answer responses |

---

## 🔄 Common Workflow 

Most vendor scripts follow a **three-step pattern** controlled in the script's `__main__` section:

### 1. 📊 Make CSV (Extract/Transform)

```python
# loader.make_csv(delimiter=",")
```

This step:
- 🔍 **Extracts data** from your vendor's EMR system
- 🔄 **Transforms data** into Canvas-compatible format
- 📝 **Writes CSV files** with proper headers and data structure
- ✅ **Applies business logic** and data cleaning rules

### 2. ✅ Validate (Quality Check)

```python
# loader.validate()
```

This step:
- 🔍 **Checks data quality** against Canvas requirements
- ✅ **Validates field formats** (dates, enums, required fields)
- ⚠️ **Identifies errors** and creates error reports
- 📊 **Generates validation statistics**

### 3. 🚀 Load (Ingest to Canvas)

```python
# loader.load()
```

This step:
- 🔌 **Connects to Canvas** via FHIR/API
- 📤 **Sends validated data** to Canvas
- 📝 **Creates/updates resources** (patients, appointments, etc.)
- 📊 **Tracks results** in done/error/ignored files

---

## 🚀 **Getting Started** 

### 📋 **Quick Start Checklist**

1. ✅ **Environment Setup**
   - [ ] Install Poetry and dependencies
   - [ ] Configure `config.ini` with your environment
   - [ ] Set up Canvas instance settings

2. ✅ **Data Preparation**
   - [ ] Clone `vendor_migration` to your vendor folder
   - [ ] Prepare potential vendor API credentials
   - [ ] Set up mapping files for your data

3. ✅ **First Migration**
   - [ ] Start with `create_patients.py`
   - [ ] Validate patient data
   - [ ] Load patients into Canvas
   - [ ] Verify patient creation

4. ✅ **Continue Migration**
   - [ ] Run other data type migrations (make_csv, validate, load)
   - [ ] Monitor progress and errors
   - [ ] Review result files
   - [ ] Lock notes when complete

### 🔧 **Common Commands**

```bash
# Install dependencies
poetry install

# Activate environment
poetry shell

# Run patient migration
python data_migrations/your_vendor_migration/create_patients.py

# Run validation only
python data_migrations/your_vendor_migration/create_allergies.py

# Run full migration
python data_migrations/your_vendor_migration/create_conditions.py
```

---

## 📺 Console Output During Migration 

When running migration scripts, you'll see real-time progress updates in the console. Here's what to expect based on the actual template migration files:

### 🔍 **Validation Phase Output**

During the `validate()` step, you'll see one of these messages:

```
Some rows contained errors, please see results/errored_*_validation.json
```

**OR**

```
All rows have passed validation!
```

**What This Shows:**
- ⚠️ **Error Summary**: If validation errors exist, shows where to find detailed error logs
- ✅ **Success Confirmation**: If all rows pass validation, shows success message
- 📁 **Error File Location**: Points to specific JSON file with detailed error information
- 🔍 **No Row-by-Row Output**: Validation happens silently without individual row progress

### 🚀 **Ingestion Phase Output**

During the `load()` step, you'll see:

```
Found X records
Ingesting (1/X)
    Complete
Ingesting (2/X)
    Errored row outputing error message to file...
...
```

**What This Shows:**
- 📊 **Record Count**: Shows total records found and ready for ingestion
- 🔄 **Progress Tracking**: Displays "Ingesting (current/total)" for each record
- 📈 **Sequential Processing**: Records are processed one by one in order

### 📋 **Common Status Messages**

| Message | Meaning | 📊 Status |
|---------|---------|-----------|
| `Already did record` | Record was previously processed successfully | 🔄 Skipped |
| `Successfully made [Name]: [Canvas URL]` | Patient successfully created with direct link to patient's chart | 🎉 Success |
| `Complete` | Record successfully created | 🎉 Success |

### ⚠️ **When Rows Error or are Ignored**

When a row encounters an error or are purposely ignored during processing:

```
Ignoring row due to "[ignore reason]"
Errored row outputing error message to file...
```

**Error Handling:**
- 🚫 **Ignored rows**: Records that fail validation or business logic checks are logged to `results/ignored_*.csv`
- ❌ **Error rows**: Records that fail during API calls or data processing are logged to `results/errored_*.csv`
- 🔍 **Error details**: Full error messages and stack traces are captured for debugging
- 🔄 **Processing continues**: Migration continues with remaining records, doesn't stop on individual failures

### ✅ **Success Output Examples**

```
Successfully made John Doe: https://environment.canvasmedical.com/patient/patient_key
Complete
```

### 💡 **Tips for Monitoring**

- 🔍 **Watch for validation errors** - Check the validation error files for detailed issues
- 📊 **Monitor ingestion progress** - Ensure records are being processed sequentially
- 📁 **Check for missing files** - Lab reports and documents may show missing file warnings
- 🔄 **Look for duplicate handling** - Records already processed will show "Already did record"
- ✅ **Verify patient creation** - Successful patient creation shows direct Canvas URLs

---

## 📊 Result CSV Files 

Each migration generates comprehensive result files for **audit trails** and **progress tracking**:

### 🔍 **File Types and Purposes**

| File Type | Purpose | 📊 Content | 📁 Location |
|-----------|---------|------------|-------------|
| `ignored_*.csv` | Records that don't meet mapping criteria | Reason data was unable to be mapped | `results/` |
| `errored_*.csv` | Records that fail during processing | API failures, data conversion errors, missing dependencies | `results/` |
| `errored*_validation.json` | Records that fail validate step | Fields that failed specific validation checks | `results/` |
| `done_*.csv` | Successfully processed records | Progress tracking and duplicate prevention. | `results/` |

### 📋 **Detailed File Contents**

#### **Ignored Records** (`results/ignored_*.csv`)
- Records that don't meet validation criteria
- Common reasons: missing required fields, invalid enum values, mapping failures
- Used for data quality improvement and troubleshooting
- Shows the records Identifier from the migrated EMR, the patient identifier, and ignored reason

#### **Error Records** (`results/errored_*.csv`)
- Records that fail during processing
- Common reasons: API failures, data conversion errors, missing dependencies
- Shows the records Identifier from the migrated EMR, the patient identifier, canvas patient key, and the full error messages and stack traces for debugging

#### **Success Records** (`results/done_*.csv`)
- Successfully processed records
- Used for tracking progress and preventing duplicate processing
- Shows the records Identifier from the migrated EMR, the patient identifier, the Canvas Patient Key, and the Canvas Resource ID

---

## ✅ Common Validation Patterns 

The migration system enforces strict validation to ensure data quality and Canvas compatibility:

### 📅 **Date/Time Validation**

#### **Date Fields**
Should be able to convert to YYYY-MM-DD format. We accept:
- `YYYY-MM-DD` (ISO format - preferred)
- `YYYY-M-DD`, `YYYY-M-D` (flexible month/day)
- `YYYY/MM/DD`, `YYYY/M/DD`, `YYYY/M/D` (slash separators)
- `MM/DD/YYYY`, `M/D/YYYY`, `M/DD/YYYY` (US format)
- `MM-DD-YYYY`, `M-D-YYYY`, `M-DD-YYYY` (dash separators)
- `MM.DD.YYYY`, `M.D.YYYY`, `M.DD.YYYY` (dot separators)

#### **DateTime Fields**
- **Format**: Always in `YYYY-MM-DDTHH:MM:SS` format
- **ISO standard**: Preferred for all date/time fields
- **Timezone**: UTC recommended for consistency

### 🎯 **Enum Validation**

Certain fields are restricted to a list of choices that can be ingested. For example, the allergy severity only accepts `severe`, `mild`, `moderate`.

### ✅ **Required Field Validation**

| Field Type | Requirements | 🔍 Validation |
|------------|--------------|---------------|
| **ID fields** | Must be unique and non-empty | Used to know if the record was already ingested or not. |
| **Patient Identifier** | Must map to existing patient in `patient_id_map.json` | Reference validation |
| **Provider fields** | Must exist in `doctor_map.json` | Provider lookup |
| **Location fields** | Must exist in location mappings | Location validation |

### 📁 **File/Document Validation**

| Requirement | Description | 🔍 Validation |
|-------------|-------------|---------------|
| **Document fields** | Must contain valid file names | Filename format check |
| **File existence** | Files must exist in specified directories | Path validation |
| **File format** | Supported formats include PDF, images, HTML | Format validation |
| **Conversion** | We try to convert all files to PDF for FHIR Document Reference ingestion | Auto-conversion |

---

## 📊 Data Type Specific Details 

All our data types are ingested using **publicly available APIs**. For more information on the details of our APIs, see [Canvas API Documentation](https://docs.canvasmedical.com/api/).

---

## 👤 **Patient Migration** (`create_patients.py`) 

Patients are the **first thing** that should be loaded. When loading patients from one EMR to Canvas, we require the EMR's unique identifier to be passed. This allows us to ensure we aren't loading duplicate records and can properly link the rest of the patient's data.

After loading patients, there will be a `PHI/patient_id_map.json` file that will be used in the rest of the data type mappings to fetch which Canvas patient the record will belong to.

Patients are loaded via **FHIR Patient Create**: [Canvas Patient API](https://docs.canvasmedical.com/api/patient/)

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `First Name` | Patient's legal first name | Non-empty string |
| `Last Name` | Patient's legal last name | Non-empty string |
| `Date of Birth` | Patient's birth date | Valid date format |
| `Sex at Birth` | Patient's sex assigned at birth | Valid sex option |
| `Identifier System 1` | Unique identifier system of the Patient from migrated EMR | Non-empty string |
| `Identifier Value 1` | Unique identifier of the Patient from migrated EMR | Non-empty string |

> ⚠️ **Address Rule**: If any address fields are supplied (Address Line 1, City, State, Postal Code) then **all these address lines are required**. Canvas is unable to save an address without all the required elements.

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Middle Name` | Patient's middle name or initial | "John" |
| `Preferred Name` | Patient's preferred name/nickname | "Johnny" |
| `Address Line 1` | Primary street address | "123 Main St" |
| `Address Line 2` | Secondary address (apartment, suite, etc.) | "Apt 4B" |
| `City` | City name | "San Francisco" |
| `State` | US state code | "CA", "NY", "TX" |
| `Postal Code` | ZIP code or postal code | "94102" |
| `Country` | Country code (defaults to "US") | "US" |
| `Mobile Phone Number` | Patient's mobile phone number | "555-123-4567" |
| `Mobile Text Consent` | Whether patient consents to text messages | `true`/`false` |
| `Home Phone Number` | Patient's home phone number | "555-987-6543" |
| `Email` | Patient's email address | "john.doe@email.com" |
| `Email Consent` | Whether patient consents to email communications | `true`/`false` |
| `Timezone` | Patient's timezone | "America/New_York" |
| `Clinical Note` | Clinical notes about the patient | "Patient has diabetes" |
| `Administrative Note` | Administrative notes about the patient | "Preferred appointment time: mornings" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Date of Birth` | We attempt to convert a date string to the YYYY-MM-DD format | Multiple date formats supported |
| `Sex at Birth` | Must be valid sex code (case insensitive) | `'m'`, `'male'`, `'f'`, `'female'`, `'oth'`, `'other'`, `'unk'`, `'unknown'` |
| `State` | Must be valid US state 2 letter abbreviation | `'CA'`, `'NY'`, `'TX'`, etc. |
| `Postal Code` | Must be valid postal code format. We take the first 5 digits | `'94102'`, `'10001'` |
| `Phone Numbers` | Must be valid phone number format. We take the first 10 digits | `'555-123-4567'` |
| `Email` | Must be valid email format | `'john.doe@email.com'` |
| `Mobile Text Consent`, `Email Consent` | Boolean values | `true`/`false`, `t`/`f`, `y`/`n`, `yes`/`no` |

---

## 📝 **Command Type Migrations**

In Canvas, we store clinical data in what we call **Commands**. For data migration purposes, we like to create a historical data migration note on the patient's timeline to insert all the commands into. 

There are some data types where you can specify a unique note to insert the command into, but we **recommend inserting the allergies, medications, conditions, immunizations, and family history all into one note**. These commands will populate the **Patient Summary** on the LHS of the patient's chart, making it easy to see the summary of what was migrated over for each patient.

We keep track of each patient's historical data migration note in the `mappings/historical_note_map.json` file as they are created. At the end of the migration, you can use the `update_data_migration_note.py` script to **lock all these notes**.

---

## 🚫 **Allergy Migration** (`create_allergies.py`) 

Allergies keep track of specific patient allergy intolerance records. These are commands inserted into a data migration note. These are loaded via **FHIR Allergy Intolerance**: [Canvas Allergy API](https://docs.canvasmedical.com/api/allergyintolerance/)

Canvas requires allergies to have an **FDB code** so that proper drug interaction warnings will be shown when trying to prescribe medications. We have created helper code to assist in mapping an allergy name or rxnorm code to FDB codes (See our mapping section below). 

However, it is not always easy to map allergies to specific codings, so there are options:
- If you want the allergy to appear in the **Allergy Patient Summary Section**, we use the generic `1-143` FDB code, if you pass the allergy text to the `Original Name` attribute, it will display in the free text attribute.Once you see that patient again, you can enter-in-error the generic one and properly record their allergy
- Or you can always use the **Questionnaire Response Data Type** to capture these allergies in a questionnaire to not lose history

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the allergy record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Clinical Status` | Allergy status | `'active'` or `'inactive'` |
| `Type` | Allergy type | `'allergy'` or `'intolerance'` |
| `FDB Code` | First DataBank code (required for Canvas ingestion) | Valid FDB code |
| `Name` | Allergy name/description | Non-empty string |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Onset Date` | When the allergy started (YYYY-MM-DD format) | `'2020-01-15'` |
| `Free Text Note` | Additional notes about the allergy | "Started at age 5." |
| `Reaction` | Description of allergic reaction | "Hives and difficulty breathing" |
| `Recorded Provider` | Provider who recorded the allergy | Must exist in `doctor_map.json` |
| `Severity` | Allergy severity | `'mild'`, `'moderate'`, or `'severe'` |
| `Original Name` | Vendor's original allergy name for comment field | Preserve vendor-specific terminology if you need to keep historical context. |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Clinical Status` | Must be exactly 'active' or 'inactive' | `'active'`, `'inactive'` |
| `Type` | Must be exactly 'allergy' or 'intolerance' | `'allergy'`, `'intolerance'` |
| `Severity` | Must be exactly 'mild', 'moderate', or 'severe' | `'mild'`, `'moderate'`, `'severe'` |
| `Onset Date` | Should be in date format (YYYY-MM-DD) | `'2020-01-15'` |
| `FDB Code` | Must be valid First DataBank code for Canvas ingestion | `'1-143'`, `'2-12345'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | If Recorded Provider provided it must exist in `doctor_map.json` | Provider lookup |

---

## 🩺 **Condition Migration** (`create_conditions.py`) 

Conditions keep track of specific patient problems/conditions that are both active or resolved. These are commands inserted into a data migration note. **Active conditions** will be Diagnose commands, while **resolved conditions** will be Past Medical History commands. These are loaded via **FHIR Condition**: [Canvas Condition API](https://docs.canvasmedical.com/api/condition/)

We require all conditions to have an **ICD-10 coding**. We have helper functions to confirm that your code is accepted by Canvas and there are functions to help you find the correct ICD10 code (see the mapping section below).

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `ICD-10 Code` | Standard ICD-10 diagnosis code | Valid ICD-10 format |
| `Clinical Status` | Condition status | `'active'` or `'resolved'` |


### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `ID` | Unique identifier for the condition record | Non-empty string |
| `Onset Date` | When the condition started (YYYY-MM-DD format) | `'2019-06-20'` |
| `Free text notes` | Additional notes about the condition | "Patient reports chest pain" |
| `Resolved Date` | When the condition was resolved (YYYY-MM-DD format) | `'2020-03-15'` |
| `Recorded Provider` | Provider who recorded the condition | Must exist in `doctor_map.json` |
| `Name` | Condition name/description | "Type 2 Diabetes Mellitus" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Clinical Status` | Must be exactly 'active' or 'resolved' | `'active'`, `'resolved'` |
| `Onset Date`, `Resolved Date` | Should be in date format (YYYY-MM-DD) | `'2019-06-20'` |
| `ICD-10 Code` | Must be valid ICD-10 code format | `'E119'`, `'I10'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |

---

## 💊 **Medication Migration** (`create_medications.py`) 

Medications are commands inserted into a data migration note. These are loaded via **FHIR Medication Statement**: [Canvas Medication API](https://docs.canvasmedical.com/api/medicationstatement/)

Canvas medications are coded to use an **FDB code** so that proper drug interaction warnings will be shown. We have created helper code to assist in mapping medication names or RxNorm codes to FDB codes (See our mapping section below). But if medications are unable to map, they can be ingested as free text / unstructured. 

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the medication record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Rxnorm/FDB Code` | Tells whether the medication should be ingested unstructured or with a coding.  | Must be unstructured or map to an FDB Code |
| `Name` | Medication name/description | Non-empty string |
| `Clinical Status` | Medication status | `'active'`, `'inactive'`, `'completed'` |


### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Onset Date` | When the medication started (YYYY-MM-DD format) | `'2020-01-15'` |
| `Free Text Note` | Additional notes about the medication | "Take with food" |
| `Recorded Provider` | Provider who prescribed the medication | Must exist in `doctor_map.json` |
| `Original Code` | Vendor's original medication code | Preserve vendor-specific coding that helps with mapping |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Clinical Status` | Must be valid status (enum validation) | `'active'`, `'inactive'`, `'completed'` |
| `Onset Date` | Should be in date format (YYYY-MM-DD) | `'2020-01-15'` |
| `Rxnorm / FDB Code` | Must be able to map to a valid First DataBank code for Canvas ingestion | `'2-12345'`, `'2-67890'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | If Recorded Provider provided it must exist in `doctor_map.json` | Provider lookup |

---

## 💉 **Immunization Migration** (`create_immunizations.py`) 

Immunizations are commands inserted into a data migration note. These are loaded via **FHIR Immunization**: [Canvas Immunization API](https://docs.canvasmedical.com/api/immunization/)

Canvas supports both **coded immunizations** (with CVX codes) and **unstructured immunizations** (free text). If a CVX code is provided, it will be used for proper vaccine tracking. If no CVX code is provided, the immunization will be ingested as unstructured text.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the immunization record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Date Performed` | Date of immunization (YYYY-MM-DD format) | Valid date format |
| `Immunization Text` | Vaccine name/description | Non-empty string |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `CVX Code` | Vaccine Administered code for structured coding | `'140'`, `'207'`, `'110'` |
| `Comment` | Additional notes about the immunization | "Administered in left deltoid" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Date Performed` | Must be valid date format (YYYY-MM-DD) | `'2024-01-15'` |
| `CVX Code` | Optional - if provided, must be valid CVX code | `'140'`, `'207'`, `'110'`, `'03'`, `'08'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |

---

## 👨‍👩‍👧‍👦 **Family History Migration** (`create_family_history.py`) 

Family history is loaded via **FHIR Family Member History**: [Canvas Family Member History API](https://docs.canvasmedical.com/api/familymemberhistory/)

We can ingest these commands as either unstructured data or SNOMED diagnosis codes. These are commands inserted into a data migration note.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `id` | Unique identifier for the family history record | Non-empty string |
| `patient` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `relative_coding` | SNOMED CT code for family relationship | Must be valid SNOMED CT code from relationship map |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `comment` | Additional notes about the family history | "Father had heart attack at age 50" |
| `icd_code` | ICD-10 code for the condition | "I21.9", "E11.9" |
| `diagnosis_description` | Human-readable condition description | "Acute myocardial infarction", "Type 2 diabetes" |

> **⚠️ Important**: At least one of `icd_code` OR `diagnosis_description` must be provided. If both are missing, the record will be ignored during migration.

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `relative_coding` | Must be valid SNOMED CT code for family relationships | `'72705000'`, `'66839005'`, `'27733009'`, etc |
| `icd_code` | Should be valid ICD-10 code (dots are automatically removed) | `'I21.9'`, `'E11.9'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |

### 👨‍👩‍👧‍👦 **Some Common Family Relationship Codes**

| Relationship | SNOMED CT Code | Description |
|--------------|----------------|-------------|
| **Mother** | `72705000` | Mother |
| **Father** | `66839005` | Father |
| **Sister** | `27733009` | Sister |
| **Brother** | `70924004` | Brother |
| **Daughter** | `66089001` | Daughter |
| **Son** | `65616008` | Son |
| **Maternal Grandmother** | `394859001` | Maternal grandmother |
| **Paternal Grandfather** | `394856008` | Paternal grandfather |
| **Maternal Grandfather** | `394857004` | Maternal grandfather |
| **Paternal Grandmother** | `394858009` | Paternal grandmother |
| **Maternal Aunt** | `442051000124109` | Maternal aunt |
| **Paternal Uncle** | `442041000124107` | Paternal uncle |
| **Maternal Uncle** | `442031000124102` | Maternal uncle |
| **Paternal Aunt** | `442061000124106` | Paternal aunt |
| **Great Grandmother** | `78652007` | Great grandmother |
| **Great Grandfather** | `50261002` | Great grandfather |
---

## 📅 **Appointment Migration** (`create_appointments.py`) 

Appointments are loaded via **FHIR Appointment**: [Canvas Appointment API](https://docs.canvasmedical.com/api/appointment/)

There is work to do in order to map both historical/past appointments and then future appointments that will take place after go live. 

Past/historical appointments can be loaded with the Historical Data Migration note type if you want to just capture when this patient was seen. Since we migrate commands into one note typically, these appointment notes will be empty. They are more just to see in the patient timeline when a patient has visited. Past appointments where the status are fulfilled will have the note in patient's timeline be checked-in and locked. 

We recommend skipping any appointments that were cancelled or rescheduled as they do not appear in the patient's timeline. 

For future appointments, we recommend loading this closer to go live date to make it easier to not keep track of any potential rescheduling. You will want to ensure future appointments are loaded with the correct appointment/note type and have a status of `booked` so that the note stays in a pre checked-in state. 

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the appointment record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Location` | Appointment location (must map to existing location) | Must be valid Canvas location ID |
| `Provider` | Provider for the appointment (must map to existing provider) | Must exist in `doctor_map.json` |
| `Start Date / Time` | Appointment start time (YYYY-MM-DDTHH:MM:SS format) | Valid datetime format |
| `End Date/Time` | Appointment end time | Valid datetime format |
| `Appointment Type` | Type of appointment | Must be a Canvas Note Type |
| `Appointment Type System` | System for appointment type coding | Valid coding system |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Reason for Visit Code` | Coded reason for the visit | Must be a RFV coding in Canvas |
| `Reason for Visit Text` | Text description of visit reason | "Annual physical examination" |
| `Meeting Link` | Virtual meeting link (for telehealth) | "https://zoom.us/j/123456789" |
| `Duration` | Duration of the appointment in minutes | "60" (minutes) |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Start Date / Time` | Must be valid datetime format (YYYY-MM-DDTHH:MM:SS) | `'2024-01-15T09:00:00'` |
| `Status` | Must be exactly 'booked' or 'fulfilled' | `'booked'`, `'fulfilled'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Location mapping` | Location must be a valid Canvas Practice Location ID | Location lookup |
| `Provider mapping` | Provider must exist in `doctor_map.json` | Provider lookup |
| `Appointment Type and System` | Must be a Canvas Note Type | Note type validation |
| `Reason for Visit Code` | Must be a RFV coding in Canvas | RFV coding validation |

---

## 🏥 **Coverage Migration** (`create_coverages.py`) 

Coverages are ingested with the **FHIR Coverage**: [Canvas Coverage API](https://docs.canvasmedical.com/api/coverage/)

Coverages appear in the **Patient's Profile Page**. If the patient's subscriber is not self, the subscriber must exist in Canvas as a patient. The payor ID must map to an Insurer that is set up in the Canvas Instance.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the coverage record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Subscriber` | Insurance subscriber patient identifier (must be a patient that exists in Canvas) | Must exist in Canvas |
| `Member ID` | Insurance member ID | Non-empty string |
| `Coverage Start Date` | When coverage began (YYYY-MM-DD format) | Valid date format |
| `Payor ID` | Insurance payor identifier | Must exist in `payor_map.json` |
| `Order` | Coverage priority order (1-5) | Must be '1', '2', '3', '4', or '5' |
| `Relationship to Subscriber` | Must be exactly 'self', 'child', 'spouse', 'other', or 'injured' | `'self'`, `'child'`, `'spouse'`, `'other'`, `'injured'` |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Type` | Type of coverage | `'medical'`, `'dental'`, `'vision'` |
| `Group Number` | Insurance group number | "GRP123456" |
| `Plan Name` | Insurance plan name | "PPO" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Coverage Start Date` | Must be valid date format (YYYY-MM-DD) | `'2024-01-01'` |
| `Order` | Must be exactly '1', '2', '3', '4', or '5' | `'1'`, `'2'`, `'3'`, `'4'`, `'5'` |
| `Relationship to Subscriber` | Must be exactly 'self', 'child', 'spouse', 'other', or 'injured' | `'self'`, `'child'`, `'spouse'`, `'other'`, `'injured'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Payor mapping` | Payor ID must exist in `payor_map.json` and be set up in Canvas Admin | Payor lookup |

---

## 📄 **Document Migration** (`create_documents.py`) 

Documents are loaded via **FHIR Document Reference**: [Canvas Document API](https://docs.canvasmedical.com/api/documentreference/). You can ingest both Administrative and Clinical Documents for a patient. You will need to map the document you are trying to ingest to the correct documents types.

Administrative type documents show up in the triple dot > Documents page next to the patient name in their chart. While clinical documents show up in the Medical Record Panel section on the RHS of the chart. 

We will try to convert images and HTML to PDF for FHIR Document Reference ingestion.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the document record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Category` | Document category | `patientadministrativedocument` or `uncategorizedclinicaldocument`
| `Type` | Type of document | Must be valid LOINC code |
| `Clinical Date` | Relevant date of the document | Should be valid date format (YYYY-MM-DD) |
| `Document` | Path to the document file | File must exist at specified path |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Description` | Document title | "Medical Records" |
| `Comment` | Additional comments about the document | `Faxed before appointment` |
| `Provider` | Provider associated with the document | Canvas staff ID |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Clinical Date` | Should be valid date format (YYYY-MM-DD) | `'2024-01-15'` |
| `Docuemnt` | Must point to existing file | Valid file in file dir |
| `Category` | Document category | `patientadministrativedocument` or `uncategorizedclinicaldocument` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | If Author provided it must exist in `doctor_map.json` | Provider lookup |
| `Type` | Type of document | Must be supported LOINC code |

### 📁 **Supported File Formats**

| Format | Support | Notes |
|--------|---------|-------|
| **PDF** | ✅ Full support | Native format, no conversion needed |
| **Images** | ✅ Supported | JPEG, PNG, GIF, BMP, TIFF |
| **HTML** | ⚠️ Limited | Attempted to convert to PDF during ingestion, may lose css styling |
| **Text** | ✅ Supported | Converted to PDF during ingestion |
| **Word Documents** | ⚠️ Limited | May require manual conversion to PDF |

---

## 🧪 **Lab Report Migration** (`create_lab_reports.py`) 

Lab reports are loaded via **FHIR DiagnosticReport**: [Canvas Lab Report API](https://docs.canvasmedical.com/api/labreport/)

These will show up in the **Lab Report Panel section** of the patient RHS of the chart. Canvas can only ingest PDFs, so the template_migration code has helper functions to convert image files to PDF.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the lab report record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Lab Date` | Date of lab test (YYYY-MM-DD format) | Valid date format |
| `Document` | JSON array of file paths to lab report documents | Must be valid JSON array of existing files |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Lab Test Name` | Name of the lab test performed | "Complete Blood Count", "Comprehensive Metabolic Panel" |
| `Lab LOINC Code` | LOINC code for the lab test | `'58410-2'`, `'24323-8'` |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Lab Date` | Must be valid date format (YYYY-MM-DD) | `'2024-01-15'` |
| `Document` | Must be valid JSON array of file paths | `["lab_report_1.pdf"]` |
| `Lab LOINC Code` | If provided, should be valid LOINC code | `'58410-2'`, `'24323-8'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |

### 📁 **Document Handling**

- **File Format**: Canvas only accepts PDF files
- **Image Conversion**: Template automatically converts images (JPEG, PNG, etc.) to PDF
- **Missing Files**: Script will log missing files and skip records with missing documents
- **Base64 Encoding**: Documents are automatically converted to base64 for FHIR ingestion

---

## ❤️ **Vitals Migration** (`create_vitals.py`) 

Vital commands are typically inserted into the patient's timeline in to Vital Data Import notes according the the `created_at` timestamp so you can see a patient's vitals over time easily.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `id` | Unique identifier for the vital sign record | Non-empty string |
| `patient` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `created_at` | Date/time when vital was recorded (YYYY-MM-DDTHH:MM:SS format) | Valid datetime format |

### 🔧 **Optional Fields**

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `height` | Patient height measurement | "68", "72.5" |
| `weight_lbs` | Patient weight in pounds | "150", "175.3" |
| `body_temperature` | Body temperature reading | "98.6", "101.2" |
| `blood_pressure_systole` | Systolic blood pressure | "120", "140" |
| `blood_pressure_diastole` | Diastolic blood pressure | "80", "90" |
| `pulse` | Heart rate/pulse | "72", "85" |
| `respiration_rate` | Respiratory rate | "16", "20" |
| `oxygen_saturation` | Oxygen saturation percentage | "98", "95" |
| `created_by` | Provider who recorded the vital | Must exist in `doctor_map.json` |
| `comment` | Additional notes about the vitals | "Patient was anxious during measurement" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `created_at` | Must be valid datetime format (YYYY-MM-DDTHH:MM:SS) | `'2024-01-15T09:00:00'` |
| `height` | Numeric value (inches) | `'68'`, `'72.5'` |
| `weight_lbs` | Numeric value (pounds, decimal for ounces) | `'150'`, `'175.3'` (3 = 3/16 lbs) |
| `blood_pressure_systole`, `blood_pressure_diastole` | Integer values | `'120'`, `'80'` |
| `pulse`, `respiration_rate`, `oxygen_saturation` | Integer values | `'72'`, `'16'`, `'98'` |
| `body_temperature` | Numeric value (Fahrenheit) | `'98.6'`, `'101.2'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | If created_by provided it must exist in `doctor_map.json` | Provider lookup |

### 💡 **How It Works**

- **Vital Data Import Notes**: Creates dedicated notes for vital sign data with timestamp-based organization
- **Weight Conversion**: Automatically converts decimal pounds to pounds and ounces (e.g., 175.3 → 175 lbs, 3 oz)
- **Integer Validation**: Ensures numeric vital values are valid integers for blood pressure, pulse, respiration, and oxygen saturation
- **Note Locking**: Automatically locks vital import notes after successful command creation
- **Fallback Provider**: Uses Canvas bot as fallback if provider mapping fails
- **Data Validation**: Ignores records where all vital values are null/empty
---

## 💬 **Message Migration** (`create_messages.py`) 

If you want to load historical messages between a patient and practitioner, you can use the **FHIR Communication**: [Canvas Communication API](https://docs.canvasmedical.com/api/communication/) to ingest historical messages.

These will show up in the **Patient's timeline** as message notes. If you will be using the **Patient Portal feature** of Canvas, the messages will also appear in the portal for the patient to see historical messages.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the message record | Non-empty string |
| `Timestamp` | When the message was sent (YYYY-MM-DDTHH:MM:SS format) | Valid datetime format |
| `Recipient` | Message recipient (either staff or patient) | Valid recipient identifier |
| `Sender` | Message sender (either staff or patient) | Valid sender identifier |
| `Text` | Message content | Non-empty string |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Timestamp` | Must be valid datetime format (YYYY-MM-DDTHH:MM:SS) | `'2024-01-15T14:30:00'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | Provider must exist in `doctor_map.json` | Provider lookup |

---

## ✅ **Consent Migration** (`create_consents.py`) 

If Consents are configured in your instance and you want to migrate over if the patient consent was rejected or active, you can use the **FHIR Consent**: [Canvas Consent API](https://docs.canvasmedical.com/api/consent/) endpoint to ingest these records.

Consents appear on the **Patient's Profile page**.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the consent record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `Status` | Consent status (active/rejected) | Must be 'active' or 'rejected' |
| `Code` | Consent code (must be configured in the Canvas Settings) | Must be valid consent code |
| `Date` | Date of consent (YYYY-MM-DD format) | Valid date format |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `Status` | Must be exactly 'active' or 'rejected' | `'active'`, `'rejected'` |
| `Date` | Must be valid date format (YYYY-MM-DD) | `'2024-01-15'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |

---

## 📝 **HPI Migration** (`create_hpi.py`) 

HPI commands capture a narrative field and can be dropped in any note as an HPI command. If you pass the Note ID parameter, it will drop the command in that note. If no Note ID is provided, it will create a new note on the patient's timeline using the DOS, provider, location, and note type name fields.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the HPI record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `DOS` | Date of service (YYYY-MM-DDTHH:MM:SS format) | Valid datetime format |
| `Narrative` | HPI narrative content | Non-empty string |

### 🔧 **Optional Fields**

Used to know which note to insert the HPI command into.

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Location` | Location where HPI was recorded | Must be a Canvas Practice Location ID |
| `Provider` | Provider who recorded the HPI | Must exist in `doctor_map.json` |
| `Note Type Name` | Type of HPI note | "History of Present Illness" |
| `Note ID` | Associated note identifier if note already exists | Canvas note ID |
| `Note Title` | Title of the HPI note | "HPI - Chest Pain" |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `DOS` | Must be valid datetime format (YYYY-MM-DDTHH:MM:SS) | `'2024-01-15T09:00:00'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | Provider must exist in `doctor_map.json` | Provider lookup |
| `Location mapping` | Must be a Canvas Practice Location ID | Location validation |

---

## 📋 **Questionnaire Response Migration** (`create_questionnaire_response.py`) 

When mapping data between EMRs, sometimes a different EMR concept is not captured well in Canvas. We typically try to save these things to a **questionnaire response**. Any data that is question or answer can be saved here. You will need to set up the Questionnaires you want to use with your Implementation Leader.

If you pass the Note ID parameter, it will drop the command in that note. If no Note ID is provided, it will create a new note on the patient's timeline using the DOS, provider, location, and note type name fields.

### ✅ **Required Fields**

| Field | Description | 🔍 Validation |
|-------|-------------|---------------|
| `ID` | Unique identifier for the questionnaire response record | Non-empty string |
| `Patient Identifier` | Patient identifier (must map to existing patient) | Must exist in `patient_id_map.json` |
| `DOS` | Date of service (YYYY-MM-DDTHH:MM:SS format) | Valid datetime format |
| `Questionnaire ID` | Identifier for the questionnaire | Must be valid questionnaire ID |

### 🔧 **Optional Fields**

Note fields are used to know which note to insert the HPI command into.

| Field | Description | 📊 Example |
|-------|-------------|------------|
| `Provider` | Provider who administered the questionnaire | Must exist in `doctor_map.json` |
| `Location` | Location where questionnaire was completed | Must be a Canvas Practice Location ID |
| `Note Type Name` | Type of questionnaire note | "Patient Assessment" |
| `Note ID` | Associated note identifier | Canvas note ID |
| `Note Title` | Title of the questionnaire note | "Health Assessment" |
| `Questions` | Question ID and answer map | `{"4e425e62-6f05-42c9-8dd2-e99d091b2905": [{"valueString": "Former Tobacco User"}]}` |

### 📋 **Data Format Requirements**

| Field Type | Requirements | ✅ Accepted Values |
|------------|--------------|-------------------|
| `DOS` | Must be valid datetime format (YYYY-MM-DDTHH:MM:SS) | `'2024-01-15T09:00:00'` |
| `Patient mapping` | Patient Identifier must exist in `patient_id_map.json` | Reference validation |
| `Provider mapping` | Provider must exist in `doctor_map.json` | Provider lookup |
| `Location mapping` | Must be a Canvas Practice Location ID | Location validation |

---

## 🗂️ **Mapping** 

### 🔍 **Specific Coding Mapping**

Some of the Canvas Data Types require specific types of mapping:
- **Medications/Allergies** want **FDB** (First DataBank) codes
- **Conditions** want **ICD-10** codes  

But it isn't always easy to map concepts from one EMR to another. We have tried to create helper scripts to assist in your mappings.

#### 🚫 **Allergy Mapping**

Allergies require **FDB codes** for proper drug interaction warnings. We provide helper scripts to map:
- Allergy names to FDB codes
- RxNorm codes to FDB codes
- Generic fallback codes for unmapped allergies

#### 💊 **Medication Mapping**

Medications require **FDB codes** for drug safety. We provide helper scripts to map:
- Medication names to FDB codes
- RxNorm codes to FDB codes
- Generic fallback codes for unmapped medications

#### 🩺 **Condition Mapping**

Conditions require **ICD-10 codes** for proper diagnosis coding. We provide helper scripts to map:
- Condition names to ICD-10 codes
- SNOMED CT codes to ICD-10 codes
- Validation of existing ICD-10 codes

#### 👨‍👩‍👧‍👦 **Family History Mapping**

Family history requires **SNOMED CT codes** for proper relationship coding. We provide helper scripts to map:
- Relationship terms to SNOMED CT codes
- Family member types to standard codes
- Validation of existing SNOMED CT codes

### 🛠️ **Interactive Mapping Review Tools**

We've created powerful interactive tools to help you review and refine your mappings. These tools are located in `data_migrations/template_migration/mapping_review.py` and provide a unified interface for managing all your coding mappings.

#### 🎯 **What These Tools Do**

The MappingReview system helps you:
- **Review unmapped concepts** that need attention
- **Search for appropriate codes** using the Coding Lookup Plugin APIs
- **Map concepts to multiple options** when exact matches aren't available
- **Validate existing mappings** for completeness
- **Handle special cases** like generic allergies or unstructured medications

#### 🔧 **Available Review Classes**

| Class | Purpose | Special Features |
|-------|---------|------------------|
| **`AllergyReview`** | Review allergy mappings | Generic fallback option, FDB + RxNorm search |
| **`MedicationReview`** | Review medication mappings | Unstructured fallback, combined name + code search |
| **`ConditionReview`** | Review condition mappings | ICD-10 + SNOMED CT search, text-based matching |

#### 🔄 **Integration with Create Scripts**

The `create_allergies.py`, `create_medications.py`, and `create_conditions.py` scripts **inherit from these Review classes** and utilize them in their main workflow. Here's how it works:

##### **1. Create Map Scripts First**
Before running the main create scripts, you'll run specialized mapping scripts that:
- **Extract unmapped concepts** from your vendor data
- **Initialize the Review classes** with your mapping files
- **Run interactive mapping sessions** to populate your coding maps
- **Save the mappings** for use in the main create scripts

##### **2. Main Create Scripts Use the Mappings**
Once your mappings are populated, the main create scripts:
- **Load the completed mappings** from your mapping files
- **Apply the mappings** to transform vendor codes to Canvas-compatible codes
- **Handle unmapped concepts** gracefully (skip, use defaults, or log for review)

##### **3. Complete Workflow**
```
1. Run create_*_map script (e.g., create_allergy_map.py)
   ↓
2. Interactive mapping session using Review classes (map and review functions)
   ↓
3. Populated mapping files (e.g., allergy_coding_map.json)
   ↓
4. Run main create script with make_csv, validate, load functions (e.g., create_allergies.py)
   ↓
5. Data migration with complete mappings
```

##### **4. Available Mapping Scripts**

| Script | Purpose | Creates/Updates |
|--------|---------|-----------------|
| **`create_allergy_map.py`** | Map allergy concepts to FDB codes | `allergy_coding_map.json` |
| **`create_medication_map.py`** | Map medication concepts to FDB codes or unstructured | `medication_coding_map.json` |
| **`create_condition_map.py`** | Map condition concepts to ICD-10 codes | `condition_coding_map.json` |

> 💡 **Pro Tip**: Run these mapping scripts **before** your main data migration to ensure all concepts are properly mapped. This prevents data loss and improves migration quality.

##### **5. Step-by-Step Mapping Process**

Each mapping script follows this exact workflow, but with different method names:

**For Allergies (`create_allergies.py`):**
```python
# 1. Create the allergy map from unique concepts in your data source
loader.create_allergy_map()

# 2. Use the map function to search and map concepts to template format
loader.map()

# 3. Review and manually decide on unmapped items
loader.review()
```

**For Medications (`create_medications.py`):**
```python
# 1. Create the medication map from unique concepts in your data source
loader.create_medication_map()

# 2. Use the map function to search and map concepts to template format
loader.map()

# 3. Review and manually decide on unmapped items
loader.review()
```

**For Conditions (`create_conditions.py`):**
```python
# 1. Create the condition map from unique concepts in your data source
loader.create_condition_map()

# 2. Use the map function to search and map concepts to template format
loader.map()

# 3. Review and manually decide on unmapped items
loader.review()
```

**What Each Step Does:**
- **`create_*_map()`**: Extracts unique concepts from your vendor data and initializes the appropriate mapping file
- **`map()`**: Searches for each concept using the Coding Lookup Plugin APIs and attempts automatic mapping
- **`review()`**: Interactive session for manually reviewing and mapping concepts that couldn't be automatically resolved

> 🔍 **Note**: Each create script inherits from its respective Review class (`AllergyReview`, `MedicationReview`, `ConditionReview`), so you have access to all the interactive mapping tools during the review phase.

#### 🚀 **Key Features**

##### **Smart Search Strategies**
- **Allergies**: Text search with concept type categorization
- **Medications**: Combined RxNorm code + text search, fallback to individual searches
- **Conditions**: ICD-10 code search with text fallback

##### **Interactive Mapping Options**
- **Single mapping**: Map one concept to one result
- **Multiple mapping**: Map one concept to multiple results for user choice
- **Skip mapping**: Remove concepts that don't need mapping
- **Special options**: Generic allergies, unstructured medications

##### **Automatic Code Detection**
- **RxNorm codes**: Automatically detected from search terms
- **ICD-10 codes**: Automatically detected from search terms
- **Text search**: Fallback when codes aren't available

#### 📖 **How to Use Individually from Create Scripts**

##### **1. Initialize the Review Tool**
```python
from data_migrations.template_migration.mapping_review import AllergyReview

# For allergies
reviewer = AllergyReview(
    environment="your_environment",
    path_to_mapping_file="mappings/allergy_coding_map.json"
)

# For medications
from data_migrations.template_migration.mapping_review import MedicationReview
reviewer = MedicationReview(
    environment="your_environment", 
    path_to_mapping_file="mappings/medication_coding_map.json"
)

# For conditions
from data_migrations.template_migration.mapping_review import ConditionReview
reviewer = ConditionReview(
    environment="your_environment",
    path_to_mapping_file="mappings/condition_coding_map.json"
)
```
> 🔍 **Note**: The environment is where you loaded the Coding Lookup Plugin

##### **2. Run Mapping Searches**
```python
# To search for concepts already in the JSON file 
reviewer.map()

# Or map a passed it list of concepts
reviewer.map(ls=["concept_name|code"])
```

##### **2. Review Mappings Interactively**
```python
# Interactive review - shows each unmapped concept
reviewer.review()
```

### 👁️‍🗨️ **What You'll See During Review**

#### **Single Concept Mapping**
```
Looking at row 1/5

Escitalopram Oxalate Oral Tablet 10 MG|

1) escitalopram 10 mg tablet
2) escitalopram 5 mg tablet
3) escitalopram 20 mg tablet
4) escitalopram 5 mg/5 mL oral solution
5) Lexapro 5 mg tablet
6) Lexapro 10 mg tablet
7) Lexapro 20 mg tablet

What do you want to map "Escitalopram Oxalate Oral Tablet 10 MG|" to?
Pick a number, "0" to not map into Canvas, "-1" for unstructured, "m" for multiple, or type to search: 1
```

#### **Multiple Mapping Option ("m")**
```
Looking at row 1/5

"Watermelon, Avocado, Banana"|

⚠️  No options found for this term

What do you want to map "Watermelon, Avocado, Banana" to?
Pick a number, "0" to not map into Canvas, "-1" for generic, "m" for multiple, or type to search: m

You are choosing to map "Watermelon, Avocado, Banana" as multiple different records

Type a term to search for, "done" when finished, or "abort" to skip: watermelon

🔍 Searching with parameters: {'text': 'watermelon'}

1) watermelon
2) watermelon seed

Pick a number to map to or "0" to ignore all options: 1
✅ Added: watermelon

Type a term to search for, "done" when finished, or "abort" to skip: avocado

🔍 Searching with parameters: {'text': 'avocado'}

1) avocado
2) avocado oil

Pick a number to map to or "0" to ignore all options: 1
✅ Added: avocado

Type a term to search for, "done" when finished, or "abort" to skip: banana

🔍 Searching with parameters: {'text': 'banana'}

1) banana
2) banana extract

Pick a number to map to or "0" to ignore all options: 1
✅ Added: banana

Type a term to search for, "done" when finished, or "abort" to skip: done

✅ Successfully mapped 'Watermelon, Avocado, Banana' to 3 items
```

##### **4. Available Commands**
- **Type a search term**: Supply a new search term if you don't like the options and want to find a better one.
- **Pick a number**: Selects from available options shown
- **"0"**: Skips this concept (removes from mapping). We do not want this to even get into Canvas
- **"m"**: Maps to multiple results. The concept shown actually represents multiple records. For example, if your vendor's EMR stores allergies as free text, you may see `Watermelon, Avacado, Bannana` and want to map each individual allergy to it's unique coding. 
- **"-1"**: 
    - Uses generic for allergies. This allows for the allergy to be ingested and the allergy text show in the free text command field so that it still can show in the Patient Summary section. 
    - Use unstructured for medications. This allows the medication to appear in the Patient Summary so we don't lose historical records. However, extra work will need to happen if you need to ever prescribe or refill this medication for the patient.

#### 🔄 **Workflow Example**

1. **Start Review**: `reviewer.review()`
2. **See unmapped concept**: `"Penicillin allergy|"`
3. **Search for options**: Type `penicillin` and press Enter
4. **Review results**: Choose from available options
5. **Continue**: Move to next unmapped concept
6. **Save automatically**: Mappings are saved after each decision

#### 💡 **Pro Tips**

- **Use the Coding Lookup Plugin**: The review tools automatically use the plugin APIs for accurate code searches
- **Handle multiple mappings**: When one concept could map to several options, use the "m" option
- **Generic fallbacks**: For allergies and medications that can't be precisely mapped, use generic/unstructured options
- **Batch processing**: Use `reviewer.map()` for programmatic mapping of known concepts
- **Configuration**: Set up your `config.ini` with proper API keys and URLs. Ensure the plugins are loaded into the instance.

### 🗂️ **Mapping Files**

Mapping files are located in the `mappings/` directory and define how source values from your vendor EMR map to Canvas concepts.

#### 📋 **Essential Mapping Files**

| File | Purpose | 📊 Content |
|------|---------|------------|
| `icd10_mappings.csv` | Maps ICD-10 codes to Canvas conditions | 🩺 Diagnosis codes |
| `snomed_to_icd10_map.json` | Translates SNOMED concepts to ICD-10 | 🔄 Code translations |
| `medication_coding_map.json` | Drug code normalizations | 💊 Medication codes |
| `allergy_coding_map.json` | Allergy code mappings | 🚫 Allergy codes |
| `doctor_map.json` | Provider entity linkage | 👨‍⚕️ Doctor mappings |
| `provider_id_mapping.json` | Provider ID translations | 🆔 Provider IDs |
| `location_map.json` | Location entity linkage | 🏥 Location mappings |
| `payor_map.json` | Insurance payor mappings | 🏦 Insurance mappings |

> 💡 **Pro Tip**: Update these files when new source systems or codes are introduced to maintain data quality and consistency.

---

## 🔌 **Plugins** 

There are some **Canvas SDK Plugins** in the `plugins` folder that are there to help with additional Data Migration needs.

### 👤 **Patient Metadata Management**

The Canvas SDK allows you to customize your own **Patient Metadata key-value pairs**. We created a plugin to get you started in viewing/setting your patient's metadata. 

**Features:**
- 🔍 **View existing metadata** for any patient
- ✏️ **Set custom metadata** fields and values
- 📊 **Bulk metadata operations** for multiple patients
- 🔄 **Metadata synchronization** across patient records

**Documentation**: See [Canvas Profile Additional Fields Guide](https://docs.canvasmedical.com/guides/profile-additional-fields/) for a guide on what this plugin uses. There is additional information for this plugin in the README file of the plugin.

**📁 For More Information**: See `data_migrations/plugins/patient_metadata_management/README.md` for detailed setup instructions, API usage examples, and troubleshooting guides.

### 🔍 **Coding Lookup Plugin**

The **Coding Lookup Plugin** provides standardized medical coding lookup services for Canvas. It offers APIs to search and retrieve medical codes from various coding systems.

**Available APIs:**
- 🚫 **Allergy Search**: Search by text description OR RxNorm code (mutually exclusive)
- 💊 **Medication Search**: Search by text description AND/OR RxNorm code (flexible combination)
- 🩺 **Condition Search**: Search by text description OR ICD-10 code (mutually exclusive)

**📁 For More Information**: See `data_migrations/plugins/coding_lookup/README.md` for comprehensive API documentation, example requests/responses, coding system details, and integration examples.

---

## 💡 **Best Practices** 

Follow these guidelines to ensure successful data migrations:

### 🎯 **Data Quality & Validation**

| Practice | Description | 🎯 Benefit |
|----------|-------------|-------------|
| **Validate First** | Validate data before migration to reduce errors | Fewer failed records |
| **Test Small** | Test with small datasets before full migration | Identify issues early |
| **Review Errors** | Review error logs to identify data quality issues | Continuous improvement |
| **Update Mappings** | Keep mapping files up-to-date with vendor changes | Maintain accuracy |

### 🗂️ **File Management**

| Practice | Description | 🎯 Benefit |
|----------|-------------|-------------|
| **Consistent Paths** | Use consistent file paths for documents and mappings | Avoid path errors |
| **Version Control** | Keep mapping files in version control (excluding PHI) | Track changes |
| **Backup Data** | Backup original vendor data before transformation | Data safety |
| **Document Changes** | Update field requirements when vendor data changes | Maintain documentation |

### 🔄 **Migration Process**

| Practice | Description | 🎯 Benefit |
|----------|-------------|-------------|
| **Start with Patients** | Always migrate patients first | Establish foundation |
| **Validate Each Step** | Run validation after each data type | Catch issues early |
| **Monitor Progress** | Watch console output and result files | Track success |
| **Handle Errors Gracefully** | Don't stop on individual record failures | Complete migration |

### 📊 **Quality Assurance**

| Practice | Description | 🎯 Benefit |
|----------|-------------|-------------|
| **Audit Results** | Review done/error/ignored files | Verify completeness |
| **Test Integration** | Verify data appears correctly in Canvas | Ensure usability |
| **Document Decisions** | Record mapping decisions and business rules | Future reference |
| **Plan Rollback** | Have a plan to undo changes if needed | Risk mitigation |
