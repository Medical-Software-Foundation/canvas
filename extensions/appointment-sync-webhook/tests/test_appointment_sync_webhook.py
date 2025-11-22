from unittest.mock import Mock, patch
import arrow
import pytest
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory

from appointment_sync_webhook.protocols.appointment_sync_webhook import AppointmentSyncWebhook


# Fixtures for common test data
@pytest.fixture
def mock_event():
    """Create a mock event for testing."""
    event = Mock()
    event.type = EventType.APPOINTMENT_CREATED
    event.context = {"patient": {"id": "patient-123"}}
    # Mock the target as the appointment ID
    event.target = Mock()
    event.target.id = "appointment-123"
    return event


@pytest.fixture
def mock_patient():
    """Create a patient object using PatientFactory."""
    patient = PatientFactory.create(
        first_name="John",
        last_name="Doe"
    )
    return patient


@pytest.fixture
def mock_appointment(mock_patient):
    """Create a mock appointment object with a real patient."""
    appointment = Mock()
    appointment.id = "appointment-123"
    appointment.start_time = arrow.get("2024-01-15T10:00:00Z").datetime
    appointment.duration_minutes = 30
    appointment.provider = Mock()
    appointment.provider.id = "provider-456"
    appointment.appointment_rescheduled_from = None
    # Set the patient to the real patient from PatientFactory
    appointment.patient = mock_patient
    return appointment


@pytest.fixture
def mock_http_success():
    """Create a mock HTTP response for successful requests."""
    response = Mock()
    response.ok = True
    return response


@pytest.fixture
def mock_http_failure():
    """Create a mock HTTP response for failed requests."""
    response = Mock()
    response.ok = False
    response.status_code = 500
    response.text = "Internal Server Error"
    return response


class TestAppointmentSyncWebhook:
    """Test suite for the AppointmentSyncWebhook handler."""

    @staticmethod
    def _setup_http_mock(mock_http_class, http_response):
        """Helper method to set up HTTP mock and return the instance."""
        mock_http_instance = Mock()
        mock_http_instance.post.return_value = http_response
        mock_http_class.return_value = mock_http_instance
        return mock_http_instance

    def test_responds_to_correct_events(self) -> None:
        """Test that the handler is configured to respond to appointment lifecycle events."""
        expected_events = [
            EventType.Name(EventType.APPOINTMENT_CREATED),
            EventType.Name(EventType.APPOINTMENT_CANCELED),
            EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
        ]
        assert AppointmentSyncWebhook.RESPONDS_TO == expected_events

    def test_no_webhook_url_configured(self, mock_event) -> None:
        """Test that handler returns empty list when WEBHOOK_URL is not configured."""
        handler = AppointmentSyncWebhook(event=mock_event)
        # Mock the secrets attribute directly on the instance
        handler.secrets = {}
        result = handler.compute()
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_appointment_created_success(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_appointment,
        mock_patient,
        mock_http_success
    ) -> None:
        """Test successful webhook notification for APPOINTMENT_CREATED event."""
        # Setup mocks
        mock_appointment_class.objects.get.return_value = mock_appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify HTTP post was called
        mock_http_instance.post.assert_called_once()
        call_args = mock_http_instance.post.call_args

        # Check webhook URL
        assert call_args[0][0] == "https://example.com/webhook"

        # Check payload structure
        payload = call_args[1]['json']
        assert payload['event_type'] == 'appointment_created'
        assert payload['appointment']['id'] == 'appointment-123'
        assert payload['appointment']['provider_id'] == 'provider-456'
        assert payload['appointment']['duration_minutes'] == 30
        assert 'timestamp' in payload
        # Patient details come from appointment.patient now
        assert payload['patient']['id'] == str(mock_patient.id)
        assert payload['patient']['first_name'] == 'John'
        assert payload['patient']['last_name'] == 'Doe'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_appointment_canceled(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_appointment,
        mock_http_success
    ) -> None:
        """Test webhook notification for APPOINTMENT_CANCELED event."""
        # Setup mocks
        mock_appointment_class.objects.get.return_value = mock_appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create event with CANCELED type
        event = Mock()
        event.type = EventType.APPOINTMENT_CANCELED
        event.context = {"patient": {"id": "patient-123"}}
        event.target = Mock()
        event.target.id = "appointment-123"

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify payload has correct event type
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        assert payload['event_type'] == 'appointment_canceled'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_appointment_no_showed(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_appointment,
        mock_http_success
    ) -> None:
        """Test webhook notification for APPOINTMENT_NO_SHOWED event."""
        # Setup mocks
        mock_appointment_class.objects.get.return_value = mock_appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create event with NO_SHOWED type
        event = Mock()
        event.type = EventType.APPOINTMENT_NO_SHOWED
        event.context = {"patient": {"id": "patient-123"}}
        event.target = Mock()
        event.target.id = "appointment-123"

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify payload has correct event type
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        assert payload['event_type'] == 'appointment_no_showed'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_rescheduled_appointment(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_http_success
    ) -> None:
        """Test webhook notification for rescheduled appointment (detected via appointment_rescheduled_from)."""

        # Setup mock original appointment
        mock_original_appointment = Mock()
        mock_original_appointment.id = "original-appointment-123"
        mock_original_appointment.start_time = arrow.get("2024-01-10T10:00:00Z").datetime
        mock_original_appointment.duration_minutes = 30
        mock_original_appointment.provider = Mock()
        mock_original_appointment.provider.id = "provider-456"
        mock_original_appointment.patient = Mock()
        mock_original_appointment.patient.id = "patient-123"

        # Setup mock new appointment (rescheduled)
        mock_new_appointment = Mock()
        mock_new_appointment.id = "appointment-456"
        mock_new_appointment.start_time = arrow.get("2024-01-15T10:00:00Z").datetime
        mock_new_appointment.duration_minutes = 30
        mock_new_appointment.provider = Mock()
        mock_new_appointment.provider.id = "provider-456"
        mock_new_appointment.appointment_rescheduled_from = Mock()
        mock_new_appointment.appointment_rescheduled_from.id = "original-appointment-123"

        # Setup mock to return different appointments based on ID
        def get_appointment(id):
            if id == "appointment-456":
                return mock_new_appointment
            elif id == "original-appointment-123":
                return mock_original_appointment
            raise Exception(f"Appointment {id} not found")

        mock_appointment_class.objects.get.side_effect = get_appointment

        # Setup HTTP mock
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create event with different target
        event = Mock()
        event.type = EventType.APPOINTMENT_CREATED
        event.context = {"patient": {"id": "patient-123"}}
        event.target = Mock()
        event.target.id = "appointment-456"

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify payload has rescheduled event type and original appointment data
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        assert payload['event_type'] == 'appointment_rescheduled'
        assert 'original_appointment' in payload['appointment']
        assert payload['appointment']['original_appointment']['id'] == 'original-appointment-123'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_webhook_http_failure(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_appointment,
        mock_http_failure
    ) -> None:
        """Test handling of HTTP failure when sending webhook."""
        # Setup mocks
        mock_appointment_class.objects.get.return_value = mock_appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_failure)

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Should still return empty list even on failure
        assert result == []
        mock_http_instance.post.assert_called_once()

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_appointment_fetch_error(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_http_success
    ) -> None:
        """Test handling when appointment details cannot be fetched."""
        # Setup mock to raise exception
        mock_appointment_class.objects.get.side_effect = Exception("Appointment not found")
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify minimal payload was sent with error field
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        assert payload['event_type'] == 'appointment_created'
        assert payload['appointment']['id'] == 'appointment-123'
        assert payload['appointment']['patient_id'] == 'patient-123'
        assert payload['error'] == 'Could not fetch full appointment details'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_appointment_without_patient(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_http_success
    ) -> None:
        """Test handling when appointment has no patient assigned."""
        # Create an appointment without a patient
        appointment = Mock()
        appointment.id = "appointment-123"
        appointment.start_time = arrow.get("2024-01-15T10:00:00Z").datetime
        appointment.duration_minutes = 30
        appointment.provider = Mock()
        appointment.provider.id = "provider-456"
        appointment.appointment_rescheduled_from = None
        appointment.patient = None  # No patient assigned

        # Setup mocks
        mock_appointment_class.objects.get.return_value = appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify payload was sent without patient details
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        # Patient section should not be in payload since appointment.patient is None
        assert 'patient' not in payload
        assert payload['event_type'] == 'appointment_created'
        assert payload['appointment']['id'] == 'appointment-123'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_patient_fetch_error(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_http_success
    ) -> None:
        """Test handling when patient details cannot be accessed."""
        # Create an appointment with a patient that raises an exception when accessing attributes
        appointment = Mock()
        appointment.id = "appointment-123"
        appointment.start_time = arrow.get("2024-01-15T10:00:00Z").datetime
        appointment.duration_minutes = 30
        appointment.provider = Mock()
        appointment.provider.id = "provider-456"
        appointment.appointment_rescheduled_from = None
        # Set up patient that raises exception when accessing first_name or last_name
        patient_mock = Mock()
        patient_mock.id = "patient-123"
        # Make first_name and last_name properties that raise exceptions
        type(patient_mock).first_name = property(lambda self: (_ for _ in ()).throw(Exception("Patient attribute error")))
        type(patient_mock).last_name = property(lambda self: (_ for _ in ()).throw(Exception("Patient attribute error")))
        appointment.patient = patient_mock

        # Setup mocks
        mock_appointment_class.objects.get.return_value = appointment
        mock_http_instance = self._setup_http_mock(mock_http_class, mock_http_success)

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}
        result = handler.compute()

        # Verify payload was sent without patient details (caught by exception handler)
        call_args = mock_http_instance.post.call_args
        payload = call_args[1]['json']
        # Patient section should not be in payload since exception was caught
        assert 'patient' not in payload
        assert payload['event_type'] == 'appointment_created'
        assert result == []

    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Http')
    @patch('appointment_sync_webhook.protocols.appointment_sync_webhook.Appointment')
    def test_http_exception(
        self,
        mock_appointment_class,
        mock_http_class,
        mock_event,
        mock_appointment
    ) -> None:
        """Test handling when HTTP post raises an exception."""
        # Setup mocks
        mock_appointment_class.objects.get.return_value = mock_appointment
        mock_http_instance = Mock()
        mock_http_instance.post.side_effect = Exception("Network error")
        mock_http_class.return_value = mock_http_instance

        # Create handler and mock secrets
        handler = AppointmentSyncWebhook(event=mock_event)
        handler.secrets = {"WEBHOOK_URL": "https://example.com/webhook"}

        # Call compute - should not raise exception
        result = handler.compute()

        # Should return empty list even when exception occurs
        assert result == []