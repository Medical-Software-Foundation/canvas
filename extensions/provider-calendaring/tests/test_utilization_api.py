"""Comprehensive tests for provider_scheduling utilization_api."""

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from unittest.mock import Mock, patch

from provider_scheduling.api.utilization import UtilizationAPI


class DummyRequest:
    """A dummy request object for testing UtilizationAPI."""

    def __init__(self, query_params: dict[str, str] | None = None) -> None:
        self.query_params = query_params or {}


class DummyEvent:
    """A dummy event object for testing API handlers."""

    def __init__(self, context: dict[str, object] | None = None) -> None:
        self.context = context or {}


def test_api_path_configuration() -> None:
    """Test that the API has correct path configuration."""
    assert UtilizationAPI.PATH == "/utilization"


def test_get_returns_not_found_for_invalid_provider() -> None:
    """Test GET endpoint returns 404 for non-existent provider."""
    # Create API request
    request = DummyRequest(query_params={"provider_id": "invalid-provider"})

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    with patch("provider_scheduling.api.utilization.Staff") as mock_staff_class:
        # Create a proper exception class for DoesNotExist
        mock_staff_class.DoesNotExist = Exception
        mock_staff_class.objects.get.side_effect = Exception("Provider not found")

        result = api.get()

        # Verify response
        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert b"Provider not found" in response.content


def test_get_returns_metrics_for_valid_provider() -> None:
    """Test GET endpoint returns metrics for valid provider."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-123", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Smith"
    mock_provider.dbid = 123

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        # Mock empty events and appointments
        mock_event_class.objects.filter.return_value = []
        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify response
        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b"providerId" in response.content
        assert b"provider-123" in response.content


def test_get_calculates_available_minutes_from_clinic_events() -> None:
    """Test GET endpoint calculates available minutes from clinic calendar events."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-456", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Johnson"
    mock_provider.dbid = 456

    # Create mock clinic events (2 hours total)
    now = datetime.now(timezone.utc)
    mock_event1 = Mock()
    mock_event1.starts_at = now - timedelta(hours=3)
    mock_event1.ends_at = now - timedelta(hours=2)  # 1 hour

    mock_event2 = Mock()
    mock_event2.starts_at = now - timedelta(hours=2)
    mock_event2.ends_at = now - timedelta(hours=1)  # 1 hour

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        # Return clinic events for first filter call, empty for admin events
        mock_event_class.objects.filter.side_effect = [
            [mock_event1, mock_event2],  # Clinic events
            [],  # Admin events
        ]

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify available minutes in response (120 minutes = 2 hours)
        response = result[0]
        assert b'"availableMinutes": 120' in response.content


def test_get_calculates_administrative_minutes_from_admin_events() -> None:
    """Test GET endpoint calculates administrative minutes from admin calendar events."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-789", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Admin"
    mock_provider.dbid = 789

    # Create mock admin event (30 minutes)
    now = datetime.now(timezone.utc)
    mock_admin_event = Mock()
    mock_admin_event.starts_at = now - timedelta(hours=1)
    mock_admin_event.ends_at = now - timedelta(minutes=30)  # 30 minutes

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        # Return empty clinic events, admin events for second filter call
        mock_event_class.objects.filter.side_effect = [
            [],  # Clinic events
            [mock_admin_event],  # Admin events
        ]

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify administrative minutes in response (30 minutes)
        response = result[0]
        assert b'"administrativeMinutes": 30' in response.content


def test_get_calculates_booked_minutes_from_appointments() -> None:
    """Test GET endpoint calculates booked minutes from appointments."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-booked", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Booked"
    mock_provider.dbid = 999

    # Create mock appointments (45 minutes total)
    mock_appointment1 = Mock()
    mock_appointment1.duration_minutes = 30

    mock_appointment2 = Mock()
    mock_appointment2.duration_minutes = 15

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = [mock_appointment1, mock_appointment2]
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify booked minutes in response (45 minutes)
        response = result[0]
        assert b'"bookedMinutes": 45' in response.content


def test_get_calculates_unbooked_minutes() -> None:
    """Test GET endpoint calculates unbooked minutes as available minus booked."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-unbooked", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Unbooked"
    mock_provider.dbid = 111

    # Create mock clinic event (60 minutes available)
    now = datetime.now(timezone.utc)
    mock_clinic_event = Mock()
    mock_clinic_event.starts_at = now - timedelta(hours=2)
    mock_clinic_event.ends_at = now - timedelta(hours=1)  # 60 minutes

    # Create mock appointment (20 minutes booked)
    mock_appointment = Mock()
    mock_appointment.duration_minutes = 20

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.side_effect = [
            [mock_clinic_event],  # Clinic events (60 min available)
            [],  # Admin events
        ]

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = [mock_appointment]  # 20 min booked
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify unbooked minutes in response (60 - 20 = 40 minutes)
        response = result[0]
        assert b'"unbookedMinutes": 40' in response.content


def test_get_unbooked_minutes_not_negative() -> None:
    """Test GET endpoint ensures unbooked minutes is never negative."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-overbooked", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Overbooked"
    mock_provider.dbid = 222

    # Create mock clinic event (30 minutes available)
    now = datetime.now(timezone.utc)
    mock_clinic_event = Mock()
    mock_clinic_event.starts_at = now - timedelta(minutes=30)
    mock_clinic_event.ends_at = now  # 30 minutes

    # Create mock appointment (60 minutes booked - more than available)
    mock_appointment = Mock()
    mock_appointment.duration_minutes = 60

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.side_effect = [
            [mock_clinic_event],  # 30 min available
            [],
        ]

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = [mock_appointment]  # 60 min booked
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify unbooked minutes is 0, not negative
        response = result[0]
        assert b'"unbookedMinutes": 0' in response.content


def test_get_uses_day_lookback_period() -> None:
    """Test GET endpoint uses 1 day lookback when period is 'day'."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-day", "lookback_period": "day"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Day"
    mock_provider.dbid = 333

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
        patch("provider_scheduling.api.utilization.datetime") as mock_datetime,
    ):
        mock_now = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify lookback period in response
        response = result[0]
        assert b'"lookbackPeriod": "day"' in response.content


def test_get_uses_month_lookback_period() -> None:
    """Test GET endpoint uses 30 day lookback when period is 'month'."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-month", "lookback_period": "month"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Month"
    mock_provider.dbid = 444

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify lookback period in response
        response = result[0]
        assert b'"lookbackPeriod": "month"' in response.content


def test_get_defaults_to_week_lookback_period() -> None:
    """Test GET endpoint defaults to week lookback when period is not specified."""
    # Create API request without lookback_period
    request = DummyRequest(query_params={"provider_id": "provider-default"})

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Default"
    mock_provider.dbid = 555

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Verify lookback period defaults to week
        response = result[0]
        assert b'"lookbackPeriod": "week"' in response.content


def test_get_queries_clinic_events_with_provider_name() -> None:
    """Test GET endpoint queries clinic events with correct provider name filter."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-query", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Query Test"
    mock_provider.dbid = 666

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        api.get()

        # Verify Event.objects.filter was called with calendar title starting with provider name
        calls = mock_event_class.objects.filter.call_args_list
        assert len(calls) == 2  # Clinic and Admin events

        # First call should be for Clinic events
        clinic_call = calls[0]
        assert clinic_call[1]["calendar__title__startswith"] == "Dr. Query Test: Clinic"

        # Second call should be for Admin events
        admin_call = calls[1]
        assert admin_call[1]["calendar__title__startswith"] == "Dr. Query Test: Admin"


def test_get_excludes_cancelled_and_noshowed_appointments() -> None:
    """Test GET endpoint excludes cancelled and no-showed appointments."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-exclude", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Exclude"
    mock_provider.dbid = 777

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
        patch("provider_scheduling.api.utilization.AppointmentProgressStatus") as mock_status,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_status.CANCELLED = "CANCELLED"
        mock_status.NOSHOWED = "NOSHOWED"

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        api.get()

        # Verify exclude was called with cancelled and noshowed statuses
        mock_appointment_queryset.exclude.assert_called_once()
        exclude_call = mock_appointment_queryset.exclude.call_args
        assert "CANCELLED" in exclude_call[1]["status__in"]
        assert "NOSHOWED" in exclude_call[1]["status__in"]


def test_get_handles_null_appointment_duration() -> None:
    """Test GET endpoint handles appointments with null duration."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-null", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider
    mock_provider = Mock()
    mock_provider.full_name = "Dr. Null"
    mock_provider.dbid = 888

    # Create mock appointment with None duration
    mock_appointment = Mock()
    mock_appointment.duration_minutes = None

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = [mock_appointment]
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        result = api.get()

        # Should not raise an error, booked minutes should be 0
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert b'"bookedMinutes": 0' in response.content


def test_get_queries_appointments_by_provider_dbid() -> None:
    """Test GET endpoint queries appointments using provider dbid."""
    # Create API request
    request = DummyRequest(
        query_params={"provider_id": "provider-dbid", "lookback_period": "week"}
    )

    # Create API instance
    dummy_context = {"method": "GET", "path": "/utilization"}
    api = UtilizationAPI(event=DummyEvent(context=dummy_context))  # type: ignore[arg-type]
    api.request = request

    # Create mock provider with specific dbid
    mock_provider = Mock()
    mock_provider.full_name = "Dr. DbId"
    mock_provider.dbid = 12345

    with (
        patch("provider_scheduling.api.utilization.Staff") as mock_staff_class,
        patch("provider_scheduling.api.utilization.Event") as mock_event_class,
        patch("provider_scheduling.api.utilization.Appointment") as mock_appointment_class,
    ):
        mock_staff_class.objects.get.return_value = mock_provider
        mock_staff_class.DoesNotExist = Exception

        mock_event_class.objects.filter.return_value = []

        mock_appointment_queryset = Mock()
        mock_appointment_queryset.exclude.return_value = []
        mock_appointment_class.objects.filter.return_value = mock_appointment_queryset

        api.get()

        # Verify Appointment.objects.filter was called with provider dbid
        filter_call = mock_appointment_class.objects.filter.call_args
        assert filter_call[1]["provider_id"] == 12345
