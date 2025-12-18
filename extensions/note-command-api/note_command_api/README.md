note-command-api
================

## Description

SimpleAPI endpoint that provides read-only access to Canvas notes with enhanced command data. This plugin exposes a GET endpoint that retrieves note data and enriches the note body with detailed command attributes from the Canvas data module.

## Features

- Retrieve complete note data by note ID
- Automatically enhance command entries in note body with full command attributes
- Filter empty text entries from note body
- Include comprehensive metadata:
  - Current state and state history with originator details
  - Patient information
  - Provider and originator details with staff status
  - Command attributes including originator, committer, state, and data

## API Endpoint

### GET plugin-io/api/note_command_api/note/<note_id>

Retrieves a note by ID and returns all note attributes with enhanced command data.

**Authentication:** API Key (via APIKeyAuthMixin)

**Path Parameters:**
- `note_id` (required): UUID of the note to retrieve

**Headers:**
- `authorization`: Your Canvas API key (configured via `simpleapi-api-key` secret)

**Response:** JSON object containing:
- `id`: Note UUID
- `dbid`: Database ID
- `created`: ISO timestamp
- `modified`: ISO timestamp
- `current_state`: Current note state (e.g., "LKD", "NEW")
- `state_history`: Array of state transitions with originator details
- `patient`: Patient details (id, first_name, last_name, birth_date)
- `note_type_version`: Note type metadata
- `title`: Note title
- `originator`: Note creator details
- `provider`: Provider details
- `billing_note`: Billing notes
- `related_data`: Additional metadata
- `datetime_of_service`: Service date/time
- `place_of_service`: Place of service description
- `encounter`: Encounter UUID
- `body`: Array of note body items (text and command entries)
  - Command entries include `attributes` with full command data:
    - `schema_key`: Command type
    - `state`: Command state
    - `created`, `modified`: Timestamps
    - `originator`, `committer`: User details with staff status
    - `entered_in_error_by`: User who marked as error (if applicable)
    - `origination_source`: Source of command
    - `data`: Command-specific data

**Error Responses:**
- `400 Bad Request`: Missing note_id parameter
- `404 Not Found`: Note does not exist

## Example Usage

```bash
curl -X GET "https://your-canvas-instance.com/plugin-io/api/note_command_api/note/788881ce-e451-44c3-b42d-6dbaebc999bb" \
  -H "authorization: your-api-key-here"
```

## Installation

1. Install the plugin in your Canvas instance
2. Configure the `simpleapi-api-key` secret with your API key
3. The endpoint will be available at `/note/<note_id>`

## Testing

Run tests with coverage:

```bash
uv run pytest tests/protocols/test_note_api.py --cov=note_command_api --cov-report=term-missing --cov-branch
```

Current coverage: 100%

## Configuration

**Required Secrets:**
- `simpleapi-api-key`: API key for authentication
