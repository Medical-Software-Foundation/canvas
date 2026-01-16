# High Risk Medications Plugin

A comprehensive Canvas Medical plugin that helps clinicians identify and monitor high-risk medications through real-time alerts, search annotations, and patient dashboards.

## Overview

This plugin provides multiple integrated features to improve medication safety:

1. **Search Annotations**: Adds "High Risk" labels to medications during prescribing workflows
2. **Banner Alerts**: Displays prominent alerts in the patient timeline when high-risk medications are active
3. **Patient Dashboard**: Shows a dedicated view of all active high-risk medications with real-time updates
4. **Action Button**: Quick access button in the medications section when high-risk meds are present
5. **Real-Time Updates**: WebSocket-powered live updates when medications change

## Features

### 1. Medication Search Annotations

When searching for medications in these workflows:
- **Prescribe** - Prescribing new medications
- **Refill** - Refilling existing prescriptions
- **Medication Statement** - Documenting current medications
- **Adjust Prescription** - Changing current medications

Medications matching high-risk patterns display a "High Risk" annotation in the search dropdown, alerting clinicians before prescribing.


### 2. Banner Alerts

Automatically adds/removes banner alerts in the patient timeline based on high-risk medication status:
- **Add Banner**: When patient has active high-risk medications
- **Remove Banner**: When no high-risk medications are present
- **Dynamic Content**: Lists all high-risk medications with monitoring recommendations


### 3. High Risk Medications Viewer

An interactive application accessible from:
- **App Drawer**: Launch from the applications menu
- **Action Button**: Quick access button in the medications section (only visible when high-risk meds present)

Displays:
- All active high-risk medications for the patient
- Medication name, dosage, and status
- Visual "HIGH RISK" badges
- Summary count of high-risk medications
- Educational information about monitoring requirements
- **Real-time updates via WebSocket** - automatically refreshes when medications change

### 4. Real-Time WebSocket Updates

The plugin uses WebSocket connections to provide live updates:
- Medications view refreshes automatically when prescriptions are added, stopped, or adjusted
- No page reload required
- Broadcasts on patient-specific channels
- Handles Canvas channel name validation (alphanumeric + underscores only)

**Technical Note**: Patient IDs contain dashes but Canvas channel names only allow alphanumeric characters and underscores. The plugin automatically sanitizes channel names by replacing dashes with underscores in both the broadcast protocol and client-side JavaScript.

## High-Risk Medication Patterns

The plugin monitors medications containing these terms (case-insensitive):

- **warfarin** - Anticoagulant requiring INR monitoring
- **insulin** - Blood glucose management medication
- **digoxin** - Cardiac glycoside with narrow therapeutic window
- **methotrexate** - Immunosuppressant/chemotherapy agent

Pattern matching is substring-based, so "insulin lispro 100 unit/mL" matches "insulin" and "Warfarin Sodium 5 MG" matches "warfarin".

## Architecture

### Protocols (Event Handlers)

- **`high_risk_medication_annotations.py`**: Adds "High Risk" annotations to medication search results
- **`banner_alert.py`**: Manages banner alerts in the patient timeline
- **`medication_change_broadcast.py`**: Broadcasts WebSocket notifications when medications change
- **`patient_summary_configuration.py`**: Configures patient summary section layout

### Applications

- **`high_risk_meds_viewer.py`**:
  - `HighRiskMedsViewer` - Application launcher
  - `HighRiskMedsActionButton` - Action button in medications section

### API Endpoints

- **`high_risk_meds_api.py`**:
  - `GET /plugin-io/api/high_risk_medications/high-risk-meds/{patient_id}` - HTML view of patient's high-risk medications
  - `WebSocket /plugin-io/ws/high_risk_medications/{patient_id}/` - Real-time medication change notifications

### Assets

- **`templates/high_risk_meds.html`**: HTML template for medications view
- **`templates/styles.css`**: Styles for the viewer interface
- **`templates/script.js`**: WebSocket client and view refresh logic

## Installation

If you want the application to open automatically on page load, you need to update the configuration of the Application in Settings on the Canvas UI.

## Development

### Project Structure

```
high-risk-medications/              # Container directory
├── pyproject.toml                  # Python dependencies and configuration
├── mypy.ini                        # Type checking configuration
├── tests/                          # Test suite (79 tests, 90%+ coverage)
│   ├── conftest.py                 # Shared test fixtures
│   ├── protocols/
│   │   ├── test_high_risk_medication_annotations.py
│   │   ├── test_banner_alert.py
│   │   ├── test_medication_change_broadcast.py
│   │   └── test_patient_summary_configuration.py
│   └── applications/
│       └── test_high_risk_meds_viewer.py
└── high_risk_medications/          # Plugin package
    ├── CANVAS_MANIFEST.json        # Plugin manifest
    ├── README.md                   # This file
    ├── protocols/                  # Event handlers
    ├── applications/               # UI applications
    ├── api/                        # HTTP and WebSocket endpoints
    ├── helper.py
    └── assets/                     # Static files and templates
```


### Test Coverage

The plugin has **79 comprehensive tests** with **90%+ coverage** including:
- Protocol event handlers (all medication events)
- Application and action button visibility logic
- API endpoints and WebSocket authentication
- Edge cases (null values, missing context, empty results)
- Real-time broadcast functionality


## Configuration

### Modify High-Risk Patterns

Edit the `HIGH_RISK_PATTERNS` list in the helper.py:

Example:
```python
HIGH_RISK_PATTERNS = [
    "warfarin",
    "insulin",
    "digoxin",
    "methotrexate",
    "heparin",  # Add new pattern
]
```

### Adjust Banner Alert Messages

Edit the banner text in `protocols/banner_alert.py` (remember there is a 90 char limit)

### Customize Patient Summary Layout

Modify section order in `protocols/patient_summary_configuration.py`:
```python
layout = PatientChartSummaryConfiguration(sections=[
    PatientChartSummaryConfiguration.Section.MEDICATIONS,
    # Reorder or remove sections as needed
])
```
