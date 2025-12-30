note-command-api
================

## Description

SimpleAPI endpoints that provide both read-only access and state management for Canvas notes. This plugin exposes a GET endpoint that retrieves note data with enhanced command attributes, and a POST endpoint that changes note states.

## Features

- Retrieve complete note data by note ID
- Automatically enhance command entries in note body with full command attributes
- Filter empty text entries from note body
- Change note states (lock, unlock, sign, push_charges, check_in, no_show, cancel)
- Include comprehensive metadata:
  - Current state and state history with originator details
  - Patient information
  - Provider and originator details with staff status
  - Command attributes including originator, committer, state, and data

## API Endpoints

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

**Example Usage:**

```bash
curl -X GET "https://your-canvas-instance.com/plugin-io/api/note_command_api/note/788881ce-e451-44c3-b42d-6dbaebc999bb" \
  -H "authorization: your-api-key-here"
```

### POST plugin-io/api/note_command_api/note/<note_id>/state

Changes the state of a note by executing the specified state transition effect.

**Authentication:** API Key (via APIKeyAuthMixin)

**Path Parameters:**
- `note_id` (required): UUID of the note to modify

**Query Parameters:**
- `state` (required): The state action to perform. Valid values:
  - `lock`: Lock the note for editing
  - `unlock`: Unlock the note
  - `sign`: Sign the note
  - `push_charges`: Push charges for the note
  - `check_in`: Check in the patient for the appointment
  - `no_show`: Mark the appointment as no show
  - `cancel`: Cancel the associated appointment

**Headers:**
- `authorization`: Your Canvas API key (configured via `simpleapi-api-key` secret)

**Response:** JSON object containing:
- `message`: Confirmation message with note ID and state change

**Error Responses:**
- `400 Bad Request`: Missing note_id parameter, missing state parameter, or invalid state value
- `404 Not Found`: Note does not exist
- `500 Internal Server Error`: Error executing state change effect

**Example Usage:**

```bash
# Lock a note
curl -X POST "https://your-canvas-instance.com/plugin-io/api/note_command_api/note/788881ce-e451-44c3-b42d-6dbaebc999bb/state?state=lock" \
  -H "authorization: your-api-key-here"

# Sign a note
curl -X POST "https://your-canvas-instance.com/plugin-io/api/note_command_api/note/788881ce-e451-44c3-b42d-6dbaebc999bb/state?state=sign" \
  -H "authorization: your-api-key-here"

# Cancel appointment
curl -X POST "https://your-canvas-instance.com/plugin-io/api/note_command_api/note/788881ce-e451-44c3-b42d-6dbaebc999bb/state?state=cancel" \
  -H "authorization: your-api-key-here"
```

## Installation

1. Install the plugin in your Canvas instance
2. Configure the `simpleapi-api-key` secret with your API key
3. The endpoint will be available at `/note/<note_id>`

## Testing

Run all tests with coverage:

```bash
uv run pytest tests/ --cov=note_command_api --cov-report=term-missing --cov-branch
```

Run individual test files:

```bash
# Test note retrieval API
uv run pytest tests/protocols/test_note_api.py -v

# Test note state change API
uv run pytest tests/protocols/test_change_note_state.py -v
```

Current coverage: 100%

## Configuration

**Required Secrets:**
- `simpleapi-api-key`: API key for authentication
