"""Comprehensive tests for provider_scheduling calendar_api."""

from unittest.mock import Mock, patch
from uuid import UUID

from provider_scheduling.api.calendar import CalendarAPI
from canvas_sdk.effects.calendar import CalendarType


class DummyRequest:
    """A dummy request object for testing CalendarAPI."""

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
    assert CalendarAPI.PATH == "/calendar"


def test_post_returns_existing_calendar_id() -> None:
    """Test POST endpoint returns existing calendar ID when calendar exists."""
    # Create API request
    request = DummyRequest(
        json_body={
            "provider": "provider-123",
            "providerName": "Dr. Smith",
            "location": "location-456",
            "locationName": "Main Clinic",
            "type": "Clinic",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name to return existing calendar ID
    existing_calendar_id = "existing-calendar-123"
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = existing_calendar_id

    with patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class:
        mock_calendar_class.objects = mock_queryset

        result = api.post()

    # Verify response
    assert len(result) == 1
    response = result[0]
    assert response.status_code == 200
    assert b'"calendarId": "existing-calendar-123"' in response.content


def test_post_creates_new_clinic_calendar() -> None:
    """Test POST endpoint creates new clinic calendar when none exists."""
    # Create API request
    request = DummyRequest(
        json_body={
            "provider": "provider-789",
            "providerName": "Dr. Johnson",
            "location": "location-111",
            "locationName": "North Clinic",
            "type": "Clinic",
            "description": "Weekly clinic schedule",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name to return None (no existing calendar)
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = None

    # Mock CalendarEffect
    mock_calendar_effect = Mock()
    mock_calendar_effect.create.return_value = mock_calendar_effect

    with (
        patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class,
        patch("provider_scheduling.api.calendar.CalendarEffect") as mock_calendar_effect_class,
    ):
        mock_calendar_class.objects = mock_queryset
        mock_calendar_effect_class.return_value = mock_calendar_effect

        result = api.post()

        # Verify CalendarEffect was called with correct parameters
        mock_calendar_effect_class.assert_called_once()
        call_args = mock_calendar_effect_class.call_args
        assert call_args[1]["provider"] == "provider-789"
        assert call_args[1]["type"] == CalendarType.Clinic
        assert call_args[1]["location"] == "location-111"
        assert call_args[1]["description"] == "Weekly clinic schedule"

        # Verify calendar ID is a valid UUID
        calendar_id = call_args[1]["id"]
        UUID(calendar_id)  # Will raise ValueError if not valid UUID

        # Verify create was called
        mock_calendar_effect.create.assert_called_once()

    # Verify response
    assert len(result) == 2
    assert result[0] == mock_calendar_effect
    response = result[1]
    assert response.status_code == 201
    assert b'"calendarId":' in response.content


def test_post_creates_administrative_calendar() -> None:
    """Test POST endpoint creates administrative calendar when type is Admin."""
    # Create API request
    request = DummyRequest(
        json_body={
            "provider": "provider-admin",
            "providerName": "Dr. Admin",
            "location": "",
            "locationName": "",
            "type": "Admin",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name to return None
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = None

    # Mock CalendarEffect
    mock_calendar_effect = Mock()
    mock_calendar_effect.create.return_value = mock_calendar_effect

    with (
        patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class,
        patch("provider_scheduling.api.calendar.CalendarEffect") as mock_calendar_effect_class,
    ):
        mock_calendar_class.objects = mock_queryset
        mock_calendar_effect_class.return_value = mock_calendar_effect

        api.post()

        # Verify CalendarEffect was called with Administrative type
        call_args = mock_calendar_effect_class.call_args
        assert call_args[1]["type"] == CalendarType.Administrative


def test_post_handles_empty_location() -> None:
    """Test POST endpoint handles empty location correctly."""
    # Create API request with empty location
    request = DummyRequest(
        json_body={
            "provider": "provider-999",
            "providerName": "Dr. Remote",
            "location": "",
            "locationName": "",
            "type": "Clinic",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = None

    # Mock CalendarEffect
    mock_calendar_effect = Mock()
    mock_calendar_effect.create.return_value = mock_calendar_effect

    with (
        patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class,
        patch("provider_scheduling.api.calendar.CalendarEffect") as mock_calendar_effect_class,
    ):
        mock_calendar_class.objects = mock_queryset
        mock_calendar_effect_class.return_value = mock_calendar_effect

        api.post()

        # Verify CalendarEffect was called with None for location
        call_args = mock_calendar_effect_class.call_args
        assert call_args[1]["location"] is None

        # Verify for_calendar_name was called with None for location
        for_calendar_args = mock_queryset.for_calendar_name.call_args
        assert for_calendar_args[1]["location"] is None


def test_post_queries_with_correct_calendar_name_parameters() -> None:
    """Test POST endpoint queries Calendar with correct parameters."""
    # Create API request
    request = DummyRequest(
        json_body={
            "provider": "provider-test",
            "providerName": "Dr. Test",
            "location": "loc-123",
            "locationName": "Test Location",
            "type": "Clinic",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = "calendar-exists"

    with patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class:
        mock_calendar_class.objects = mock_queryset

        api.post()

        # Verify for_calendar_name was called with correct parameters
        mock_queryset.for_calendar_name.assert_called_once_with(
            provider_name="Dr. Test",
            calendar_type=CalendarType.Clinic,
            location="Test Location",
        )


def test_post_defaults_to_clinic_type_for_unknown_type() -> None:
    """Test POST endpoint defaults to Clinic type for unknown calendar type."""
    # Create API request with unknown type
    request = DummyRequest(
        json_body={
            "provider": "provider-unknown",
            "providerName": "Dr. Unknown",
            "location": "",
            "locationName": "",
            "type": "UnknownType",
        }
    )

    # Create API instance
    dummy_context = {"method": "POST", "path": "/calendar"}
    api = CalendarAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Mock Calendar.objects.for_calendar_name
    mock_queryset = Mock()
    mock_queryset.for_calendar_name.return_value = mock_queryset
    mock_queryset.values_list.return_value = mock_queryset
    mock_queryset.last.return_value = None

    # Mock CalendarEffect
    mock_calendar_effect = Mock()
    mock_calendar_effect.create.return_value = mock_calendar_effect

    with (
        patch("provider_scheduling.api.calendar.Calendar") as mock_calendar_class,
        patch("provider_scheduling.api.calendar.CalendarEffect") as mock_calendar_effect_class,
    ):
        mock_calendar_class.objects = mock_queryset
        mock_calendar_effect_class.return_value = mock_calendar_effect

        api.post()

        # Verify CalendarEffect was called with Clinic type (default)
        call_args = mock_calendar_effect_class.call_args
        assert call_args[1]["type"] == CalendarType.Clinic
