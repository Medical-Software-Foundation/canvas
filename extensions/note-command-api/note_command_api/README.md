note-command-api
================

## Description

SimpleAPI endpoints for creating, retrieving, and managing Canvas notes. This plugin provides:
- A POST endpoint to create new notes with flexible identifier lookup
- A GET endpoint that retrieves note data with enhanced command attributes
- A POST endpoint that changes note states

## Features

- **Create notes** with flexible identifier options (lookup by ID or name)
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

### POST plugin-io/api/note_command_api/create-note

Creates a new note with flexible identifier lookup options.

**Authentication:** API Key (via APIKeyAuthMixin)

**Headers:**
- `authorization`: Your Canvas API key (configured via `simpleapi-api-key` secret)
- `Content-Type`: application/json

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `instance_id` | UUID string | No | Custom note ID. If not provided, a UUID will be generated. |
| `note_type_id` | UUID string | One of three | ID of an existing active NoteType |
| `note_type_name` | string | One of three | Name of an existing active NoteType |
| `note_type_code` | string | One of three | Code of an existing active NoteType |
| `datetime_of_service` | datetime string | Yes | e.g., "2025-02-21 23:31:42" |
| `patient_id` | UUID string | Yes | ID of an existing Patient |
| `practice_location_id` | UUID string | One of two | ID of an existing active PracticeLocation |
| `practice_location_name` | string | One of two | Full name or short name of an active PracticeLocation |
| `provider_id` | UUID string | One of two | ID of an existing active Staff member |
| `provider_name` | string | One of two | Full name (first + last) of an active Staff member |
| `title` | string | No | Custom title for the note |

**Response (202 Accepted):**
```json
{
  "message": "Note creation accepted",
  "note_id": "generated-or-provided-uuid"
}
```

**Error Responses:**
- `400 Bad Request`: Missing required fields, invalid UUIDs, or entity not found

**Example Usage:**

```bash
# Create note using IDs
curl -X POST "https://your-canvas-instance.com/plugin-io/api/note_command_api/create-note" \
  -H "authorization: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "note_type_id": "c5df4f03-58e4-442b-ad6c-0d3dadc6b726",
    "datetime_of_service": "2025-02-21 23:31:42",
    "patient_id": "5350cd20de8a470aa570a852859ac87e",
    "practice_location_id": "306b19f0-231a-4cd4-ad2d-a55c885fd9f8",
    "provider_id": "6b33e69474234f299a56d480b03476d3",
    "title": "Follow-up Visit"
  }'

# Create note using names (flexible lookup)
curl -X POST "https://your-canvas-instance.com/plugin-io/api/note_command_api/create-note" \
  -H "authorization: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "note_type_name": "Progress Note",
    "datetime_of_service": "2025-02-21 23:31:42",
    "patient_id": "5350cd20de8a470aa570a852859ac87e",
    "practice_location_name": "Main Clinic",
    "provider_name": "John Smith"
  }'
```

---

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
3. The endpoints will be available at:
   - `POST /plugin-io/api/note_command_api/create-note` - Create new notes
   - `GET /plugin-io/api/note_command_api/note/<note_id>` - Retrieve note data
   - `POST /plugin-io/api/note_command_api/note/<note_id>/state` - Change note state

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
