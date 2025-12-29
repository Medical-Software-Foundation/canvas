lab-result-api
==============

## Description

SimpleAPI endpoint that provides read-only access to Canvas lab results with comprehensive data including ordering provider, lab facility, and individual test values. This plugin exposes a GET endpoint that retrieves lab report data with all related test results.

## Features

- Retrieve complete lab report data by lab report ID
- Include ordering provider information (name, NPI)
- Include lab facility details
- Return all individual test values with results, units, and reference ranges
- Include comprehensive metadata:
  - Patient information
  - Lab test values with abnormal flags and observation status
  - Reference ranges and thresholds
  - Test codings and display names

## API Endpoint

### GET plugin-io/api/lab_result_api/lab-result/<lab_report_id>

Retrieves a lab report by ID and returns all lab data with ordering provider and test results.

**Authentication:** API Key (via APIKeyAuthMixin)

**Path Parameters:**
- `lab_report_id` (required): UUID of the lab report to retrieve

**Headers:**
- `authorization`: Your Canvas API key (configured via `simpleapi-api-key` secret)

**Response:** JSON object containing:
- `id`: Lab report UUID
- `dbid`: Database ID
- `created`: ISO timestamp
- `modified`: ISO timestamp
- `patient`: Patient details (id, first_name, last_name, birth_date)
- `ordering_provider`: Provider details (id, first_name, last_name, npi)
- `lab_facility`: Lab facility details (name)
- `originator`: Report originator details
- `lab_tests`: Array of individual test results:
  - `id`: Test value UUID
  - `test_name`: Display name of the test
  - `test_code`: Test code
  - `coding_system`: Coding system (e.g., LOINC)
  - `value`: Test result value
  - `units`: Units of measurement
  - `reference_range`: Reference range string
  - `abnormal_flag`: Abnormal flag (e.g., "high", "low")
  - `observation_status`: Status of the observation
  - `low_threshold`: Lower threshold value
  - `high_threshold`: Upper threshold value
  - `comment`: Additional comments
  - `created`: ISO timestamp
  - `modified`: ISO timestamp

**Error Responses:**
- `400 Bad Request`: Missing lab_report_id parameter
- `404 Not Found`: Lab report does not exist

## Example Usage

```bash
curl -X GET "https://your-canvas-instance.com/plugin-io/api/lab_result_api/lab-result/788881ce-e451-44c3-b42d-6dbaebc999bb" \
  -H "authorization: your-api-key-here"
```

## Installation

1. Install the plugin in your Canvas instance
2. Configure the `simpleapi-api-key` secret with your API key
3. The endpoint will be available at `/lab-result/<lab_report_id>`

## Testing

Run tests with coverage:

```bash
uv run pytest tests/protocols/test_lab_result_api.py --cov=lab_result_api --cov-report=term-missing --cov-branch
```

## Configuration

**Required Secrets:**
- `simpleapi-api-key`: API key for authentication

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it gets updated if you add, remove, or rename protocols.
