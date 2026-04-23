chronic_care_management_activity_tracker
========================================

## Description

The Chronic Care Management (CCM) Activity Tracker plugin automates tracking, documentation, and billing for chronic care management services. This plugin provides a comprehensive workflow for managing CCM activities including session tracking, patient banner alerts, and automated monthly billing.


## Installation

```
canvas install chronic-care-management-activity-tracker
```

### Features

#### 1. **CCM Session Tracking Application**
- Interactive web application for staff to log CCM activities
- Real-time session timer to track activity duration
- Captures comprehensive session data:
  - Patient and staff information
  - Activities performed (medication review, care plan updates, provider coordination, etc.)
  - Session notes and time logs
  - Cumulative monthly time tracking
- Automatically creates a "Chronic Care Management Note" with completed questionnaire

#### 2. **Patient Banner Alerts**
- Real-time banner displays on patient charts showing total CCM time logged for the current month
- Updates automatically when new CCM sessions are completed
- Visible on both the chart and profile views
- Helps providers quickly identify CCM service status

#### 3. **Patient Metadata Fields**
- Custom `CCM Diagnosis` field in patient metadata
- Used to store comma-separated ICD-10 codes for CCM-eligible diagnoses
- Displayed in patient profile for easy access and updates

#### 4. **Automated Monthly Billing**
- Cron job runs on the 1st of each month at midnight
- Processes all patients with CCM diagnoses from the previous month
- Automated workflow:
  1. Locates the most recent CCM questionnaire from last calendar month
  2. Checks total time logged (must be ≥20 minutes)
  3. Creates a "Monthly Summary" note with:
     - Author: Patient's care team member with `chronic_care_management_provider` role
     - Practice location: Patient's most recent note location
     - Date: Current date
     - All ICD-10 diagnoses from patient's CCM metadata field
  4. Adds appropriate billing line items:
     - **20-39 minutes**: CPT 99490 × 1
     - **40-59 minutes**: CPT 99490 × 1, CPT 99439 × 1
     - **60-79 minutes**: CPT 99490 × 1, CPT 99439 × 2
     - And so on for each additional 20-minute increment

### Configuration

**Required Setup:**
1. **Note Types:**
   - `chronic_care_management_note` - For individual CCM session notes
   - `monthly_summary` - For automated monthly billing notes

2. **Questionnaire:**
   - Code: `ccm_session_questionnaire`
   - Tracks patient name, staff name, date, activities, notes, time logs, session duration, and monthly total

3. **Care Team Role:**
   - Code: `chronic_care_management_provider`
   - System: `INTERNAL`
   - Assign to care team members authorized to provide CCM services

4. **Patient Metadata:**
   - Key: `ccm_diagnosis`
   - Value: Comma-separated ICD-10 codes (e.g., "E11.69, Z75.9, F33.9")

### Plugin Components

- **Application**: `ccmat_app.py` - Web UI for CCM session tracking
- **API**: `ccmat_api.py` - Backend API for session management
- **Protocols**:
  - `ccmat_diagnosis_protocol.py` - Adds CCM Diagnosis metadata field
  - `ccmat_monthly_banner_protocol.py` - Displays monthly time banner
- **Cron Task**: `ccmat_monthly_cron.py` - Automated monthly billing
- **Assets**: HTML, CSS, JavaScript, and questionnaire YAML

### Billing Logic

The automated billing follows CMS guidelines for Chronic Care Management (CCM) services:

- **CPT 99490**: First 20 minutes of clinical staff time per calendar month
- **CPT 99439**: Each additional 20 minutes of clinical staff time

**Examples:**
- 25 minutes → 99490 × 1
- 63 minutes → 99490 × 1, 99439 × 2
- 45 minutes → 99490 × 1, 99439 × 1

### Important Notes

CCM time calculations only use the latest version of the questionnaire. Editing `ccmat_questionnaire.yml` and reinstalling the plugin creates a new questionnaire version.

## Running Tests

```
uv run pytest tests/
```

## See it in action

[Click Here to See a Demo](https://app.arcade.software/flows/pA2VYmIKWmgj7U58WIGL/view)

[![](https://images.prismic.io/canvas-website/aep20cBOoF08xQuq_screenshot-JA-35M-04232026013360.jpg?auto=format,compress)](https://app.arcade.software/flows/pA2VYmIKWmgj7U58WIGL/view)
