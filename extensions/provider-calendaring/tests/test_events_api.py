"""Comprehensive tests for provider_scheduling events_api."""

from datetime import datetime
from unittest.mock import Mock, patch

from provider_scheduling.api.events import CalendarEventsAPI
from canvas_sdk.effects.calendar import DaysOfWeek, EventRecurrence


class DummyRequest:
    """A dummy request object for testing CalendarEventsAPI."""

    def __init__(self, json_body: dict[str, object] | None = None) -> None:
        self._json_body = json_body or {}

    def json(self) -> dict[str, object]:
        """Return the mocked JSON body."""
        return self._json_body


class DummyEvent:
    """A dummy event object for testing API handlers."""

    def __init__(self, context: dict[str, object] | None = None) -> None:
        self.context = context or {}


def test_api_path_configuration() -> None:
    """Test that the API has correct path configuration."""
    assert CalendarEventsAPI.PATH == "/events"


def test_post_creates_calendar_event_with_basic_data() -> None:
    """Test POST endpoint creates calendar event with basic required data."""
    # Create API request
    request = DummyRequest(
        json_body={
            "calendar": "calendar-123",
            "title": "Morning Clinic",
            "startTime": "2025-12-05T09:00:00Z",
            "endTime": "2025-12-05T17:00:00Z",
            "recurrenceFrequency": "",
            "recurrenceInterval": None,
            "recurrenceDays": [],
            "recurrenceEndsAt": "",
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.create.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        # Mock arrow.get to return predictable datetime
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 5, 9, 0, 0)
            if "09:00" in x
            else datetime(2025, 12, 5, 17, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        result = api.post()

        # Verify Event was called with correct parameters
        mock_event_class.assert_called_once()
        call_args = mock_event_class.call_args
        assert call_args[1]["calendar_id"] == "calendar-123"
        assert call_args[1]["title"] == "Morning Clinic"
        assert call_args[1]["starts_at"] == datetime(2025, 12, 5, 9, 0, 0)
        assert call_args[1]["ends_at"] == datetime(2025, 12, 5, 17, 0, 0)
        assert call_args[1]["recurrence_frequency"] is None
        assert call_args[1]["recurrence_interval"] is None
        assert call_args[1]["recurrence_days"] is None
        assert call_args[1]["recurrence_ends_at"] is None
        assert call_args[1]["allowed_note_types"] == []

        # Verify create was called
        mock_event_effect.create.assert_called_once()

    # Verify response
    assert len(result) == 2
    assert result[0] == mock_event_effect
    response = result[1]
    assert response.status_code == 201


def test_post_creates_event_with_weekly_recurrence() -> None:
    """Test POST endpoint creates event with weekly recurrence pattern."""
    # Create API request
    request = DummyRequest(
        json_body={
            "calendar": "calendar-456",
            "title": "Weekly Schedule",
            "startTime": "2025-12-05T08:00:00Z",
            "endTime": "2025-12-05T16:00:00Z",
            "recurrenceFrequency": "WEEKLY",
            "recurrenceInterval": 1,
            "recurrenceDays": ["MO", "WE", "FR"],
            "recurrenceEndsAt": "2026-12-05T16:00:00Z",
            "allowedNoteTypes": ["note-type-1", "note-type-2"],
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.create.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        # Mock arrow.get to return predictable datetimes
        def mock_arrow_get(time_str: str) -> Mock:
            if "08:00" in time_str:
                return Mock(datetime=datetime(2025, 12, 5, 8, 0, 0))
            elif "16:00" in time_str and "2025" in time_str:
                return Mock(datetime=datetime(2025, 12, 5, 16, 0, 0))
            else:
                return Mock(datetime=datetime(2026, 12, 5, 16, 0, 0))

        mock_arrow.get.side_effect = mock_arrow_get
        mock_event_class.return_value = mock_event_effect

        result = api.post()

        # Verify Event was called with recurrence parameters
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_frequency"] == EventRecurrence("WEEKLY")
        assert call_args[1]["recurrence_interval"] == 1
        assert call_args[1]["recurrence_days"] == [
            DaysOfWeek("MO"),
            DaysOfWeek("WE"),
            DaysOfWeek("FR"),
        ]
        assert call_args[1]["recurrence_ends_at"] == datetime(2026, 12, 5, 16, 0, 0)
        assert call_args[1]["allowed_note_types"] == ["note-type-1", "note-type-2"]

    # Verify response
    assert len(result) == 2
    response = result[1]
    assert response.status_code == 201


def test_post_handles_null_recurrence_ends_at() -> None:
    """Test POST endpoint handles null recurrence end date correctly."""
    # Create API request
    request = DummyRequest(
        json_body={
            "calendar": "calendar-789",
            "title": "Indefinite Schedule",
            "startTime": "2025-12-05T10:00:00Z",
            "endTime": "2025-12-05T18:00:00Z",
            "recurrenceFrequency": "DAILY",
            "recurrenceInterval": 1,
            "recurrenceDays": [],
            "recurrenceEndsAt": None,
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.create.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 5, 10, 0, 0)
            if "10:00" in x
            else datetime(2025, 12, 5, 18, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        api.post()

        # Verify recurrence_ends_at is None
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_ends_at"] is None


def test_patch_updates_calendar_event() -> None:
    """Test PATCH endpoint updates existing calendar event."""
    # Create API request
    request = DummyRequest(
        json_body={
            "eventId": "event-123",
            "title": "Updated Schedule",
            "startTime": "2025-12-06T09:00:00Z",
            "endTime": "2025-12-06T17:00:00Z",
            "recurrenceFrequency": "WEEKLY",
            "recurrenceInterval": 2,
            "recurrenceDays": ["TU", "TH"],
            "recurrenceEndsAt": "2026-06-06T17:00:00Z",
            "allowedNoteTypes": ["type-a", "type-b"],
        }
    )

    # Create API instance
    dummy_context = {"method": "PATCH", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.update.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        # Mock arrow.get to return predictable datetimes
        def mock_arrow_get(time_str: str) -> Mock:
            if "09:00" in time_str:
                return Mock(datetime=datetime(2025, 12, 6, 9, 0, 0))
            elif "17:00" in time_str and "2025" in time_str:
                return Mock(datetime=datetime(2025, 12, 6, 17, 0, 0))
            else:
                return Mock(datetime=datetime(2026, 6, 6, 17, 0, 0))

        mock_arrow.get.side_effect = mock_arrow_get
        mock_event_class.return_value = mock_event_effect

        result = api.patch()

        # Verify Event was called with update parameters
        mock_event_class.assert_called_once()
        call_args = mock_event_class.call_args
        assert call_args[1]["event_id"] == "event-123"
        assert call_args[1]["title"] == "Updated Schedule"
        assert call_args[1]["starts_at"] == datetime(2025, 12, 6, 9, 0, 0)
        assert call_args[1]["ends_at"] == datetime(2025, 12, 6, 17, 0, 0)
        assert call_args[1]["recurrence_frequency"] == EventRecurrence("WEEKLY")
        assert call_args[1]["recurrence_interval"] == 2
        assert call_args[1]["recurrence_days"] == [DaysOfWeek("TU"), DaysOfWeek("TH")]
        assert call_args[1]["recurrence_ends_at"] == datetime(2026, 6, 6, 17, 0, 0)
        assert call_args[1]["allowed_note_types"] == ["type-a", "type-b"]

        # Verify update was called
        mock_event_effect.update.assert_called_once()

    # Verify response
    assert len(result) == 2
    assert result[0] == mock_event_effect
    response = result[1]
    assert response.status_code == 200


def test_patch_updates_event_without_recurrence() -> None:
    """Test PATCH endpoint updates event without recurrence pattern."""
    # Create API request
    request = DummyRequest(
        json_body={
            "eventId": "event-456",
            "title": "One-Time Event",
            "startTime": "2025-12-10T14:00:00Z",
            "endTime": "2025-12-10T15:00:00Z",
            "recurrenceFrequency": "",
            "recurrenceInterval": None,
            "recurrenceDays": [],
            "recurrenceEndsAt": None,
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "PATCH", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.update.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 10, 14, 0, 0)
            if "14:00" in x
            else datetime(2025, 12, 10, 15, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        api.patch()

        # Verify Event was called without recurrence
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_frequency"] is None
        assert call_args[1]["recurrence_interval"] is None
        assert call_args[1]["recurrence_days"] is None
        assert call_args[1]["recurrence_ends_at"] is None


def test_delete_removes_calendar_event() -> None:
    """Test DELETE endpoint removes calendar event."""
    # Create API request
    request = DummyRequest(json_body={"eventId": "event-to-delete"})

    # Create API instance
    dummy_context = {"method": "DELETE", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.delete.return_value = mock_event_effect

    with patch("provider_scheduling.api.events.Event") as mock_event_class:
        mock_event_class.return_value = mock_event_effect

        result = api.delete()

        # Verify Event was called with event_id
        mock_event_class.assert_called_once_with(event_id="event-to-delete")

        # Verify delete was called
        mock_event_effect.delete.assert_called_once()

    # Verify response
    assert len(result) == 2
    assert result[0] == mock_event_effect
    response = result[1]
    assert response.status_code == 200


def test_post_handles_empty_recurrence_frequency() -> None:
    """Test POST endpoint handles empty recurrence frequency correctly."""
    # Create API request
    request = DummyRequest(
        json_body={
            "calendar": "calendar-999",
            "title": "Simple Event",
            "startTime": "2025-12-15T12:00:00Z",
            "endTime": "2025-12-15T13:00:00Z",
            "recurrenceFrequency": "",
            "recurrenceInterval": None,
            "recurrenceDays": [],
            "recurrenceEndsAt": "",
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.create.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 15, 12, 0, 0)
            if "12:00" in x
            else datetime(2025, 12, 15, 13, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        api.post()

        # Verify Event was called with None for recurrence fields
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_frequency"] is None
        assert call_args[1]["recurrence_interval"] is None
        assert call_args[1]["recurrence_days"] is None


def test_post_converts_recurrence_interval_to_int() -> None:
    """Test POST endpoint converts recurrence interval to integer."""
    # Create API request with string interval
    request = DummyRequest(
        json_body={
            "calendar": "calendar-int-test",
            "title": "Interval Test",
            "startTime": "2025-12-20T10:00:00Z",
            "endTime": "2025-12-20T11:00:00Z",
            "recurrenceFrequency": "DAILY",
            "recurrenceInterval": "3",  # String instead of int
            "recurrenceDays": [],
            "recurrenceEndsAt": None,
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.create.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 20, 10, 0, 0)
            if "10:00" in x
            else datetime(2025, 12, 20, 11, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        api.post()

        # Verify recurrence_interval was converted to int
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_interval"] == 3
        assert isinstance(call_args[1]["recurrence_interval"], int)


def test_patch_converts_recurrence_interval_to_int() -> None:
    """Test PATCH endpoint converts recurrence interval to integer."""
    # Create API request with string interval
    request = DummyRequest(
        json_body={
            "eventId": "event-patch-int",
            "title": "Patch Interval Test",
            "startTime": "2025-12-25T14:00:00Z",
            "endTime": "2025-12-25T15:00:00Z",
            "recurrenceFrequency": "WEEKLY",
            "recurrenceInterval": "2",  # String instead of int
            "recurrenceDays": [],
            "recurrenceEndsAt": None,
            "allowedNoteTypes": [],
        }
    )

    # Create API instance
    dummy_context = {"method": "PATCH", "path": "/events"}
    api = CalendarEventsAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Event effect
    mock_event_effect = Mock()
    mock_event_effect.update.return_value = mock_event_effect

    with (
        patch("provider_scheduling.api.events.arrow") as mock_arrow,
        patch("provider_scheduling.api.events.Event") as mock_event_class,
    ):
        mock_arrow.get.side_effect = lambda x: Mock(
            datetime=datetime(2025, 12, 25, 14, 0, 0)
            if "14:00" in x
            else datetime(2025, 12, 25, 15, 0, 0)
        )
        mock_event_class.return_value = mock_event_effect

        api.patch()

        # Verify recurrence_interval was converted to int
        call_args = mock_event_class.call_args
        assert call_args[1]["recurrence_interval"] == 2
        assert isinstance(call_args[1]["recurrence_interval"], int)
