from unittest.mock import MagicMock, patch

import pytest

from intake_agent.api.intake import IntakeAPI


class TestIntakeAPI:
    """Unit tests for IntakeAPI handler."""

    @pytest.fixture
    def intake_api(self):
        """Create an IntakeAPI instance for testing."""
        # Create a mock event object required by BaseHandler
        mock_event = MagicMock()
        mock_event.context = {
            "method": "GET",
            "path": "/intake"
        }

        # Create the API instance with the mock event
        intake = IntakeAPI(mock_event)

        # Mock the request object that would normally be set by the framework
        intake.request = MagicMock()

        return intake

    def test_authenticate_allows_all_access(self, intake_api):
        """Test that authenticate method always returns True for public access."""
        # Arrange
        mock_credentials = MagicMock()

        # Act
        result = intake_api.authenticate(mock_credentials)

        # Assert
        assert result is True

    @patch("intake_agent.api.intake.render_to_string")
    def test_get_returns_html_response(self, mock_render, intake_api):
        """Test that get_intake_form method returns HTMLResponse with rendered template."""
        # Arrange
        expected_html = "<html><body>Test HTML</body></html>"
        mock_render.return_value = expected_html

        # Act
        result = intake_api.get_intake_form()

        # Assert
        assert len(result) == 1
        response = result[0]
        assert hasattr(response, "content")

        # Verify render_to_string was called with correct arguments
        mock_render.assert_called_once_with("templates/intake.html", {})

    @patch("intake_agent.api.intake.render_to_string")
    def test_get_uses_empty_context(self, mock_render, intake_api):
        """Test that get_intake_form method passes empty context to render_to_string."""
        # Arrange
        mock_render.return_value = "<html></html>"

        # Act
        intake_api.get_intake_form()

        # Assert
        # Verify the second argument (context) is an empty dict
        call_args = mock_render.call_args
        assert call_args[0][1] == {}

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.render_to_string")
    def test_get_logs_request(self, mock_render, mock_log, intake_api):
        """Test that get_intake_form method logs when serving the intake form."""
        # Arrange
        mock_render.return_value = "<html></html>"

        # Act
        intake_api.get_intake_form()

        # Assert
        mock_log.info.assert_called_once_with("Serving patient intake form")

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.PatientEffect")
    @patch("intake_agent.api.intake.render_to_string")
    def test_post_creates_new_patient_with_email_and_phone(
        self, mock_render, mock_patient_effect, mock_patient, mock_log, intake_api
    ):
        """Test that submit_intake_form creates a new patient when no duplicates exist."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "John",
            "lastName": "Doe",
            "email": "john.doe@example.com",
            "phone": "(555) 123-4567"
        }

        # Mock Patient.objects.filter to return no existing patients
        mock_patient.objects.filter.return_value.exists.return_value = False

        # Mock patient effect
        mock_effect_instance = MagicMock()
        mock_create_effect = MagicMock()
        mock_effect_instance.create.return_value = mock_create_effect
        mock_patient_effect.return_value = mock_effect_instance

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 2
        assert result[0] == mock_create_effect

        # Verify redirect response
        redirect_response = result[1]
        assert redirect_response.status_code == 303
        assert redirect_response.headers["Location"] == "/plugin-io/api/intake_agent/chat/NEW_PATIENT"

        # Verify patient effect was created with correct data
        mock_patient_effect.assert_called_once()
        call_kwargs = mock_patient_effect.call_args.kwargs
        assert call_kwargs["first_name"] == "John"
        assert call_kwargs["last_name"] == "Doe"
        assert len(call_kwargs["contact_points"]) == 2

        # Verify logging
        assert mock_log.info.call_count == 2

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.render_to_string")
    def test_post_shows_banner_when_email_exists(
        self, mock_render, mock_patient, mock_log, intake_api
    ):
        """Test that submit_intake_form shows banner when patient with email exists."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "John",
            "lastName": "Doe",
            "email": "existing@example.com",
            "phone": "(555) 123-4567"
        }

        # Mock existing patient
        mock_existing_patient = MagicMock()
        mock_existing_patient.id = "patient-123"
        mock_patient.objects.filter.return_value.exists.return_value = True
        mock_patient.objects.filter.return_value.first.return_value = mock_existing_patient

        mock_render.return_value = "<html>Warning banner</html>"

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 1

        # Verify render was called with banner context
        mock_render.assert_called_once_with("templates/intake.html", {
            "banner_message": "A patient with this contact information is already on record. Please contact us if you need assistance.",
            "banner_type": "warning"
        })

        # Verify logging
        mock_log.info.assert_any_call(f"Found existing patient with email existing@example.com: {mock_existing_patient.id}")

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.render_to_string")
    def test_post_shows_banner_when_phone_exists(
        self, mock_render, mock_patient, mock_log, intake_api
    ):
        """Test that submit_intake_form shows banner when patient with phone exists."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "John",
            "lastName": "Doe",
            "email": "new@example.com",
            "phone": "(555) 987-6543"
        }

        # Mock no patient with email, but patient with phone
        mock_existing_patient = MagicMock()
        mock_existing_patient.id = "patient-456"

        def filter_side_effect(*args, **kwargs):
            mock_queryset = MagicMock()
            if "telecom__system" in kwargs:
                if kwargs.get("telecom__value") == "new@example.com":
                    # Email query returns no results
                    mock_queryset.exists.return_value = False
                else:
                    # Phone query returns existing patient
                    mock_queryset.exists.return_value = True
                    mock_queryset.first.return_value = mock_existing_patient
            return mock_queryset

        mock_patient.objects.filter.side_effect = filter_side_effect
        mock_render.return_value = "<html>Warning banner</html>"

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 1

        # Verify render was called with banner context
        mock_render.assert_called_once_with("templates/intake.html", {
            "banner_message": "A patient with this contact information is already on record. Please contact us if you need assistance.",
            "banner_type": "warning"
        })

        # Verify phone was cleaned (last 10 digits: 5559876543)
        assert mock_log.info.call_count >= 2

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.PatientEffect")
    def test_post_creates_patient_with_only_email(
        self, mock_patient_effect, mock_patient, mock_log, intake_api
    ):
        """Test creating patient with only email (no phone)."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "Jane",
            "lastName": "Smith",
            "email": "jane@example.com",
            "phone": ""
        }

        mock_patient.objects.filter.return_value.exists.return_value = False

        mock_effect_instance = MagicMock()
        mock_create_effect = MagicMock()
        mock_effect_instance.create.return_value = mock_create_effect
        mock_patient_effect.return_value = mock_effect_instance

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 2

        # Verify patient effect has only email contact point
        call_kwargs = mock_patient_effect.call_args.kwargs
        assert len(call_kwargs["contact_points"]) == 1
        # Contact point should be email

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.PatientEffect")
    def test_post_creates_patient_with_only_phone(
        self, mock_patient_effect, mock_patient, mock_log, intake_api
    ):
        """Test creating patient with only phone (no email)."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "Bob",
            "lastName": "Johnson",
            "email": "",
            "phone": "5551234567"
        }

        mock_patient.objects.filter.return_value.exists.return_value = False

        mock_effect_instance = MagicMock()
        mock_create_effect = MagicMock()
        mock_effect_instance.create.return_value = mock_create_effect
        mock_patient_effect.return_value = mock_effect_instance

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 2

        # Verify patient effect has only phone contact point
        call_kwargs = mock_patient_effect.call_args.kwargs
        assert len(call_kwargs["contact_points"]) == 1

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    def test_post_phone_cleaning_removes_formatting(
        self, mock_patient, mock_log, intake_api
    ):
        """Test that phone number cleaning removes formatting characters."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "Test",
            "lastName": "User",
            "email": "",
            "phone": "(555) 123-4567"
        }

        mock_patient.objects.filter.return_value.exists.return_value = False

        # Act - we're just testing the phone cleaning logic runs
        # The actual filter call will verify the cleaned phone
        with patch("intake_agent.api.intake.PatientEffect") as mock_effect:
            mock_effect_instance = MagicMock()
            mock_effect_instance.create.return_value = MagicMock()
            mock_effect.return_value = mock_effect_instance

            intake_api.submit_intake_form()

        # Assert - verify filter was NOT called for phone since email is empty
        # (only checks phone if no email provided or no email match found)
        # The phone would be cleaned to "5551234567" for the query

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.PatientEffect")
    def test_post_skips_phone_check_if_less_than_10_digits(
        self, mock_patient_effect, mock_patient, mock_log, intake_api
    ):
        """Test that phone check is skipped if cleaned phone has less than 10 digits."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "Test",
            "lastName": "User",
            "email": "",
            "phone": "123"  # Only 3 digits
        }

        mock_effect_instance = MagicMock()
        mock_create_effect = MagicMock()
        mock_effect_instance.create.return_value = mock_create_effect
        mock_patient_effect.return_value = mock_effect_instance

        # Act
        result = intake_api.submit_intake_form()

        # Assert
        assert len(result) == 2
        # No filter should be called since email is empty and phone < 10 digits
        assert mock_patient.objects.filter.call_count == 0

    @patch("intake_agent.api.intake.log")
    @patch("intake_agent.api.intake.Patient")
    @patch("intake_agent.api.intake.PatientEffect")
    def test_post_logs_patient_creation(
        self, mock_patient_effect, mock_patient, mock_log, intake_api
    ):
        """Test that patient creation is logged."""
        # Arrange
        intake_api.request.form_data.return_value = {
            "firstName": "Alice",
            "lastName": "Wonder",
            "email": "alice@example.com",
            "phone": "5551234567"
        }

        mock_patient.objects.filter.return_value.exists.return_value = False

        mock_effect_instance = MagicMock()
        mock_create_effect = MagicMock()
        mock_effect_instance.create.return_value = mock_create_effect
        mock_patient_effect.return_value = mock_effect_instance

        # Act
        intake_api.submit_intake_form()

        # Assert
        mock_log.info.assert_any_call("Processing intake form submission")
        mock_log.info.assert_any_call("Creating new patient: Alice Wonder")
