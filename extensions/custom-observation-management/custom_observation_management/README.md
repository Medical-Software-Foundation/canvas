# Custom Observation Management

A Canvas plugin providing a RESTful API for managing patient observations.

## Description

This plugin exposes HTTP endpoints for retrieving and creating patient observations in Canvas. It supports flexible filtering including date range queries, making it useful for integrations that need to query observations by time period.

## Authentication

All endpoints require API key authentication. Configure the `simpleapi-api-key` secret in your Canvas instance.

## Endpoints

### GET /observation/<observation_id>

Retrieve a single observation by UUID.

**Response:** JSON object with observation details.

### GET /observations

List observations with optional filters.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `patient_id` | string | Filter by patient UUID |
| `note_dbid` | string | Filter by note database ID |
| `note_uuid` | string | Filter by note UUID |
| `name` | string | Filter by observation name (exact match) |
| `category` | string | Filter by category (comma-separated for multiple) |
| `effective_datetime_start` | string | Observations on or after this datetime (ISO 8601) |
| `effective_datetime_end` | string | Observations on or before this datetime (ISO 8601) |

**Examples:**

```
GET /observations?patient_id=abc-123-def
GET /observations?name=Blood%20Pressure&category=vital-signs
GET /observations?effective_datetime_start=2024-01-01T00:00:00Z&effective_datetime_end=2024-12-31T23:59:59Z
```

### POST /observation

Create a new observation.

**Required Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `patient_id` | string | Patient UUID |
| `name` | string | Observation name/type (e.g., "Blood Pressure") |
| `effective_datetime` | string | When the observation was taken (ISO 8601) |

**Optional Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `category` | string or string[] | Observation category (e.g., "vital-signs") |
| `value` | string | The observation value (e.g., "120/80") |
| `units` | string | Units of measurement (e.g., "mmHg") |
| `note_id` | integer | Database ID of the associated note |
| `is_member_of_id` | string | UUID of parent observation (for grouped observations) |
| `codings` | object[] | FHIR codings for the observation |
| `components` | object[] | Observation components (e.g., systolic/diastolic) |
| `value_codings` | object[] | FHIR codings for the observation value |

**Coding Object Structure:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system` | string | Yes | The coding system URI (e.g., "http://loinc.org") |
| `code` | string | Yes | The code value |
| `display` | string | Yes | Human-readable display text |
| `version` | string | No | Version of the coding system |
| `user_selected` | boolean | No | Whether the coding was user-selected |

**Component Object Structure:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Component name (e.g., "Systolic") |
| `value_quantity` | string | Yes | The component value |
| `value_quantity_unit` | string | Yes | Units for the value |
| `codings` | object[] | No | FHIR codings for this component |

**Example Request (minimal):**

```json
{
    "patient_id": "abc-123-def",
    "name": "Blood Pressure",
    "effective_datetime": "2024-06-15T10:30:00Z"
}
```

**Example Request (with all fields):**

```json
{
    "patient_id": "abc-123-def",
    "name": "Blood Pressure",
    "effective_datetime": "2024-06-15T10:30:00Z",
    "category": "vital-signs",
    "value": "120/80",
    "units": "mmHg",
    "codings": [
        {
            "system": "http://loinc.org",
            "code": "85354-9",
            "display": "Blood pressure panel"
        }
    ],
    "components": [
        {
            "name": "Systolic",
            "value_quantity": "120",
            "value_quantity_unit": "mmHg",
            "codings": [
                {
                    "system": "http://loinc.org",
                    "code": "8480-6",
                    "display": "Systolic blood pressure"
                }
            ]
        },
        {
            "name": "Diastolic",
            "value_quantity": "80",
            "value_quantity_unit": "mmHg",
            "codings": [
                {
                    "system": "http://loinc.org",
                    "code": "8462-4",
                    "display": "Diastolic blood pressure"
                }
            ]
        }
    ]
}

## Response Format

Observations are returned with the following structure:

```json
{
    "id": "observation-uuid",
    "patient": {
        "id": "patient-uuid",
        "first_name": "John",
        "last_name": "Doe"
    },
    "name": "Blood Pressure",
    "category": "vital-signs",
    "value": "120/80",
    "units": "mmHg",
    "effective_datetime": "2024-06-15T10:30:00+00:00",
    "note": {
        "id": "note-uuid",
        "dbid": 12345,
        "datetime_of_service": "2024-06-15T10:00:00+00:00"
    },
    "codings": [],
    "components": [],
    "value_codings": []
}
```

## Important Note

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it gets updated if you add, remove, or rename protocols.
