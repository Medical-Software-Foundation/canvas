# CPT Billing API Plugin

A Canvas Medical plugin that provides a SimpleAPI endpoint for programmatically adding CPT billing line items to clinical notes.

## Features

- **SimpleAPI Endpoint**: RESTful API for adding billing codes to notes
- **API Key Authentication**: Secure access with Bearer token authentication
- **CPT Code Validation**: Validates codes against ChargeDescriptionMaster including expiration and effective dates
- **ICD-10 Code Linking**: Automatically links billing codes to assessments by ICD-10 codes
- **Comprehensive Error Handling**: Detailed error responses for validation failures

## Setup

Configure the API key secret in Canvas:
   - Secret name: `simpleapi-api-key`
   - Set a secure API key value

## API Documentation

### Endpoint

```
POST plugin-io/api/cpt_billing_cpt/billing/add-line-item
```

### Authentication

Include an API key in the Authorization header:

```
authorization: YOUR_API_KEY
```

### Request Body

```json
{
  "note_id": "uuid-of-note",
  "cpt_code": "99213",
  "units": 1,
  "icd10_codes": ["E11.9", "I10"]
}
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `note_id` | string (UUID) | Yes | The unique identifier of the Canvas note |
| `cpt_code` | string | Yes | The CPT code to bill (e.g., "99213") |
| `units` | integer | No | Number of units (default: 1) |
| `icd10_codes` | array of strings | No | List of ICD-10 codes to link as diagnosis pointers. These codes must be billable conditions in the note footer |

### Response

#### Success Response (201 Created)

```json
{
  "status": "success",
  "message": "Billing line item sent to Canvas successfully",
  "note_id": "a74592ae-8a6c-4d0e-be07-99d3fb3713d1",
  "cpt_code": "99213",
  "units": 1,
  "found_icd10_codes": ["E11.9", "I10"],
  "not_found_icd10_codes": [],
  "assessment_ids": ["assessment-uuid-1", "assessment-uuid-2"]
}
```

#### Error Responses

**400 Bad Request** - Validation error
```json
{
  "status": "error",
  "error": "Invalid request",
  "details": "Missing required field: note_id"
}
```

**404 Not Found** - Resource not found
```json
{
  "status": "error",
  "error": "Resource not found",
  "details": "Note with ID xyz does not exist"
}
```

**422 Unprocessable Entity** - CPT code validation error
```json
{
  "status": "error",
  "error": "Invalid CPT code",
  "details": "CPT code '99999' not found in ChargeDescriptionMaster"
}
```

**500 Internal Server Error** - Unexpected error
```json
{
  "status": "error",
  "error": "Internal server error",
  "details": "An unexpected error occurred while processing the request"
}
```

## CPT Code Validation

The plugin validates CPT codes against the ChargeDescriptionMaster table:

1. **Existence**: Verifies the CPT code exists in the system
2. **Expiration**: Ensures the code is not expired (checks `expiration_date`)
3. **Effectiveness**: Ensures the code is currently effective (checks `effective_date`)

### Validation Examples

- ❌ Expired code: `expiration_date < today`
- ❌ Not yet effective: `effective_date > today`
- ✅ Valid code: `expiration_date` is None or in future, `effective_date` is None or in past

## ICD-10 Code Linking

When `icd10_codes` are provided, the plugin automatically:

1. Searches for assessments in the specified note
2. Matches assessments with conditions having the specified ICD-10 codes
3. Links the billing line item to the matching assessments

### ICD-10 Code Normalization

The plugin normalizes ICD-10 codes for matching:
- Converts to uppercase
- Removes periods (dots)

Examples:
- `"E11.9"` → matches `"E119"` or `"E11.9"`
- `"i10"` → matches `"I10"`

### Response Details

- `found_icd10_codes`: List of ICD-10 codes that were successfully matched to assessments
- `not_found_icd10_codes`: List of ICD-10 codes that could not be matched
- `assessment_ids`: List of assessment UUIDs linked to the billing line item

## Usage Examples

### Basic Billing (No ICD-10 Codes)

```bash
curl -X POST https://your-canvas-instance.com/billing/add-line-item \
  -H "authorization: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "note_id": "a74592ae-8a6c-4d0e-be07-99d3fb3713d1",
    "cpt_code": "99213",
    "units": 1
  }'
```

### Billing with ICD-10 Code Linking

```bash
curl -X POST https://your-canvas-instance.com/billing/add-line-item \
  -H "authorization: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "note_id": "a74592ae-8a6c-4d0e-be07-99d3fb3713d1",
    "cpt_code": "99213",
    "units": 1,
    "icd10_codes": ["E11.9", "I10"]
  }'
```

### Python Example

```python
import requests

url = "https://your-canvas-instance.com/billing/add-line-item"
headers = {
    "authorization": "YOUR_API_KEY",
    "Content-Type": "application/json"
}
data = {
    "note_id": "a74592ae-8a6c-4d0e-be07-99d3fb3713d1",
    "cpt_code": "99213",
    "units": 1,
    "icd10_codes": ["E11.9", "I10"]
}

response = requests.post(url, headers=headers, json=data)
print(response.json())
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest tests/ --cov=cpt_billing_api --cov-report=term-missing --cov-branch

# Run specific test file
uv run pytest tests/protocols/test_billing_api.py -v
```

### Test Coverage

Current test coverage: **93%**

The test suite includes:
- Successful billing line item creation (with and without ICD-10 codes)
- Missing required fields validation
- Invalid JSON handling
- Note not found scenarios
- CPT code validation (expired, not effective, not found)
- ICD-10 code matching and linking
- Error handling for unexpected errors

### Project Structure

```
cpt-billing-api/
├── cpt_billing_api/
│   ├── CANVAS_MANIFEST.json      # Plugin configuration
│   ├── README.md                 # Plugin documentation (this file)
│   └── protocols/
│       └── billing_api.py        # Main API handler
├── tests/
│   ├── conftest.py               # Test fixtures
│   └── protocols/
│       └── test_billing_api.py   # API handler tests
├── pyproject.toml                # Python dependencies
└── mypy.ini                      # Type checking configuration
```

## Logging

The plugin logs detailed information for debugging and monitoring:

- **Info**: Successful operations, CPT validation, assessment matching
- **Warning**: No assessments found for ICD-10 codes, validation issues
- **Error**: Unexpected errors with stack traces

Example log output:
```
INFO: CPT code '99213' validated successfully. Effective: None, Expires: Never
INFO: Found assessment abc-123 with ICD-10 code E11.9
WARNING: ICD-10 codes ['X99.9'] not found in note 12345
INFO: Adding billing line item: note_id=xyz, cpt=99213, units=1, assessment_ids=['abc-123']
```
