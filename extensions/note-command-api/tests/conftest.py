import pytest
from unittest.mock import MagicMock
from datetime import datetime

from canvas_sdk.test_utils.factories import (
    PatientFactory,
    PracticeLocationFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.note import NoteType


@pytest.fixture
def mock_event():
    """Create a mock event for handler initialization."""
    event = MagicMock()
    event.context = {"method": "GET", "path": "/note/test-id"}
    return event
@pytest.fixture
def mock_request():
    """Create a mock SimpleAPI request."""
    request = MagicMock()
    request.path_params = MagicMock()
    request.headers = {}
    request.json.return_value = {}
    return request

@pytest.fixture
def note_type():
    """Create a NoteType via objects.create (no factory in v0.84.0)."""
    return NoteType.objects.create(
        name="Progress Note",
        display="Progress Note",
        system="canvas",
        icon="note",
        category="encounter",
        rank=1,
        is_active=True,
        is_default_appointment_type=False,
        is_scheduleable=False,
        is_telehealth=False,
        is_billable=False,
        defer_place_of_service_to_practice_location=False,
        default_place_of_service="11",
        is_system_managed=False,
        is_visible=True,
        is_patient_required=True,
        allow_custom_title=False,
        is_scheduleable_via_patient_portal=False,
        unique_identifier="00000000-0000-0000-0000-000000000001",
        deprecated_at="2099-01-01 00:00:00",
        online_duration=0,
        available_places_of_service=["11"],
    )

@pytest.fixture
def patient():
    return PatientFactory.create()

@pytest.fixture
def practice_location():
    return PracticeLocationFactory.create()

@pytest.fixture
def staff():
    return StaffFactory.create()
@pytest.fixture
def mock_note():
    """Create a mock Note instance with all required fields."""
    note = MagicMock()
    note.id = "test-note-uuid-123"
    note.dbid = 456
    note.created = datetime(2025, 1, 15, 10, 0, 0)
    note.modified = datetime(2025, 1, 15, 10, 45, 0)
    mock_current_state = MagicMock()
    mock_current_state.values_list.return_value = ["LKD"]
    note.current_state = mock_current_state
    mock_state1 = MagicMock()
    mock_state1.state = "NEW"
    mock_state1.created = datetime(2025, 1, 15, 10, 0, 0)
    mock_state1.originator.person_subclass.id = "staff-uuid-1"
    mock_state1.originator.person_subclass.first_name = "John"
    mock_state1.originator.person_subclass.last_name = "Doe"
    mock_state1.originator.is_staff = True
    mock_state2 = MagicMock()
    mock_state2.state = "LKD"
    mock_state2.created = datetime(2025, 1, 15, 10, 45, 0)
    mock_state2.originator.person_subclass.id = "staff-uuid-2"
    mock_state2.originator.person_subclass.first_name = "Jane"
    mock_state2.originator.person_subclass.last_name = "Smith"
    mock_state2.originator.is_staff = True
    mock_state_history = MagicMock()
    mock_state_history.all.return_value = [mock_state1, mock_state2]
    note.state_history = mock_state_history
    note.patient.id = "patient-uuid-789"
    note.patient.first_name = "Alice"
    note.patient.last_name = "Johnson"
    note.patient.birth_date = datetime(1980, 5, 15).date()
    note.note_type_version.name = "Progress Note"
    note.note_type_version.display = "Progress Note"
    note.note_type_version.code = "progress_note"
    note.title = "Test Note"
    note.body = [
        {"type": "text", "value": ""},
        {
            "type": "command",
            "value": "prescribe",
            "data": {
                "id": 123,
                "command_uuid": "cmd-uuid-abc"
            }
        },
        {"type": "text", "value": "Free text line"},
    ]
    note.originator.person_subclass.id = "originator-uuid"
    note.originator.person_subclass.first_name = "John"
    note.originator.person_subclass.last_name = "Doe"
    note.originator.is_staff = True
    note.provider.id = "provider-uuid"
    note.provider.first_name = "Jane"
    note.provider.last_name = "Smith"
    note.billing_note = "Billing notes"
    note.related_data = {}
    note.datetime_of_service = datetime(2025, 1, 15, 9, 0, 0)
    note.place_of_service = "11"
    note.encounter.id = "encounter-uuid"
    return note
@pytest.fixture
def mock_command():
    """Create a mock Command instance with person_subclass fields."""
    command = MagicMock()
    command.id = "cmd-uuid-abc"
    command.schema_key = "prescribe"
    command.state = "committed"
    command.created = datetime(2025, 1, 15, 10, 30, 0)
    command.modified = datetime(2025, 1, 15, 10, 30, 0)
    command.originator.person_subclass.id = "cmd-originator-uuid"
    command.originator.person_subclass.first_name = "Bob"
    command.originator.person_subclass.last_name = "Wilson"
    command.originator.is_staff = True
    command.committer.person_subclass.id = "cmd-committer-uuid"
    command.committer.person_subclass.first_name = "Carol"
    command.committer.person_subclass.last_name = "Brown"
    command.committer.is_staff = True
    command.entered_in_error_by = None
    command.origination_source = "manual"
    command.data = {
        "medication": "Metformin 500mg",
        "sig": "Take 1 tablet twice daily",
        "quantity": 60,
        "refills": 3
    }
    return command
