# Plugin Specification: lab-result-api

## Problem Statement
External systems need read-only access to Canvas lab result data including all lab tests and their values. The API should expose comprehensive lab result information including ordering provider details, lab facility information, and individual test names with their corresponding values/results.

## User Stories
- As an external system, I want to retrieve lab result data by ID so that I can access detailed lab test information with ordering provider and facility details
- As an external system, I want to see all lab tests within a result so that I can process individual test values and names
- As an external system, I want to authenticate via API key so that access is secure

## Trigger
- **Event**: HTTP GET request
- **Conditions**: External system makes authenticated request with lab result ID

## Data Requirements
- **Read**:
  - LabResult (primary model)
  - LabOrder (for ordering provider and related metadata)
  - LabTest (individual test results within the lab result)
  - Provider/Staff information (for ordering provider details)
  - Lab facility information
- **Write**: None (read-only)

## Effects
- JSONResponse with lab result data

## Architecture
- **Complexity**: Simple
- **Components**:
  - 1 SimpleAPIRoute handler with APIKeyAuthMixin
  - GET endpoint: `/lab-result/<lab_result_id>`
  - Serialization methods for lab result data
- **Rationale**: Mirrors note-command-api pattern - single read-only endpoint with data enrichment, no event-driven logic needed

## Secrets/Configuration
- `simpleapi-api-key`: API key for authentication (same secret as note-command-api)

## Response Structure
```json
{
  "id": "lab-result-uuid",
  "dbid": 123,
  "created": "2025-01-15T10:30:00Z",
  "modified": "2025-01-15T10:35:00Z",
  "status": "final",
  "ordering_provider": {
    "id": "provider-uuid",
    "first_name": "Jane",
    "last_name": "Smith",
    "npi": "1234567890"
  },
  "lab_facility": {
    "name": "Quest Diagnostics",
    "identifier": "QUEST-001"
  },
  "observation_date": "2025-01-15T08:00:00Z",
  "patient": {
    "id": "patient-uuid",
    "first_name": "John",
    "last_name": "Doe",
    "birth_date": "1980-05-15"
  },
  "lab_tests": [
    {
      "id": "test-uuid-1",
      "test_name": "Hemoglobin A1c",
      "value": "6.5",
      "unit": "%",
      "reference_range": "4.0-5.6",
      "abnormal_flag": "high",
      "status": "final"
    },
    {
      "id": "test-uuid-2",
      "test_name": "Glucose",
      "value": "110",
      "unit": "mg/dL",
      "reference_range": "70-100",
      "abnormal_flag": "high",
      "status": "final"
    }
  ]
}
```

## Open Questions
- Should we include lab order information beyond ordering provider?
- Are there specific Canvas data model relationships we need to verify (LabResult → LabOrder → Provider)?
- Should we filter lab tests by status (e.g., only include final results)?

## Next Steps
1. Use canvas-sdk skill to verify exact data model structure (LabResult, LabOrder, LabTest)
2. Create plugin scaffold: `uv run canvas init lab-result-api`
3. Implement the SimpleAPI handler with serialization methods
4. Write comprehensive unit tests (targeting 90%+ coverage)
5. Security review (plugin-api-server-security skill)
6. Deploy to test instance
7. Perform UAT
