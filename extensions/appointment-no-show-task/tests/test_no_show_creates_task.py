"""Tests for the NoShowCreatesTask protocol."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

from canvas_sdk.effects.task import AddTask
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.team import Team

# Import the protocol we're testing
from appointment_no_show_task.protocols.no_show_creates_task import NoShowCreatesTask


class TestNoShowCreatesTask(unittest.TestCase):
    """Test cases for the NoShowCreatesTask protocol."""

    def setUp(self):
        """Set up test fixtures."""
        self.protocol = NoShowCreatesTask()
        # Mock secrets
        self.protocol.secrets = {"TEAM_NAME": "Admin", "LABELS": "no-show,reschedule"}

        # Mock patient
        self.mock_patient = Mock(spec=Patient)
        self.mock_patient.id = "patient-123"
        self.mock_patient.first_name = "John"
        self.mock_patient.last_name = "Doe"

        # Mock appointment
        self.mock_appointment = Mock(spec=Appointment)
        self.mock_appointment.id = "appointment-456"
        self.mock_appointment.patient = self.mock_patient
        self.mock_appointment.start_time = datetime(2025, 1, 15, 10, 30)
        self.mock_appointment.status = "no-show"

        # Mock team
        self.mock_team = Mock(spec=Team)
        self.mock_team.id = "team-789"
        self.mock_team.name = "Admin"

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_creates_task_when_appointment_is_no_show(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that a task is created when APPOINTMENT_NO_SHOWED event fires."""
        # Setup
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.return_value = self.mock_team

        # Set up protocol target (string UUID for APPOINTMENT_NO_SHOWED event)
        self.protocol.target = "appointment-456"

        # Execute
        effects = self.protocol.compute()

        # Verify
        self.assertEqual(len(effects), 1)
        mock_appointment_class.objects.get.assert_called_once_with(id="appointment-456")
        mock_team_class.objects.get.assert_called_once_with(name="Admin")

    def test_handles_missing_appointment_id(self):
        """Test that the protocol handles missing appointment ID gracefully."""
        # Setup
        self.protocol.target = None

        # Execute
        effects = self.protocol.compute()

        # Verify
        self.assertEqual(len(effects), 0)

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_handles_appointment_not_found(self, mock_appointment_class):
        """Test that the protocol handles appointment not found gracefully."""
        # Setup
        mock_appointment_class.objects.get.side_effect = Appointment.DoesNotExist
        self.protocol.target = "nonexistent-appointment"

        # Execute
        effects = self.protocol.compute()

        # Verify
        self.assertEqual(len(effects), 0)

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_creates_task_without_team_when_team_not_found(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that task is created without team assignment when team doesn't exist."""
        # Setup
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.side_effect = Team.DoesNotExist

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        effects = self.protocol.compute()

        # Verify
        self.assertEqual(len(effects), 1)

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_creates_task_without_team_when_secret_not_configured(
        self, mock_appointment_class
    ):
        """Test that task is created without team assignment when TEAM_NAME secret is missing."""
        # Setup
        self.protocol.secrets = {}  # No TEAM_NAME secret
        mock_appointment_class.objects.get.return_value = self.mock_appointment

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        effects = self.protocol.compute()

        # Verify
        self.assertEqual(len(effects), 1)

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_task_includes_patient_context(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that the task includes the correct patient context."""
        # Setup
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.return_value = self.mock_team

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        with patch.object(AddTask, "__init__", return_value=None) as mock_init:
            with patch.object(AddTask, "apply", return_value=Mock()):
                effects = self.protocol.compute()

                # Verify AddTask was initialized with correct patient_id
                mock_init.assert_called_once()
                call_kwargs = mock_init.call_args[1]
                self.assertEqual(call_kwargs["patient_id"], "patient-123")
                self.assertEqual(call_kwargs["team_id"], "team-789")
                self.assertIn("no-show", call_kwargs["labels"])
                self.assertIn("reschedule", call_kwargs["labels"])

    def test_protocol_responds_to_correct_events(self):
        """Test that the protocol is configured to respond to appointment events."""
        expected_events = [
            EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
        ]
        self.assertEqual(NoShowCreatesTask.RESPONDS_TO, expected_events)

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_custom_labels_from_secret(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that custom labels from secret are applied correctly."""
        # Setup with custom labels
        self.protocol.secrets = {
            "TEAM_NAME": "Admin",
            "LABELS": "urgent,patient-no-show,follow-up"
        }
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.return_value = self.mock_team

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        with patch.object(AddTask, "__init__", return_value=None) as mock_init:
            with patch.object(AddTask, "apply", return_value=Mock()):
                effects = self.protocol.compute()

                # Verify custom labels were used
                mock_init.assert_called_once()
                call_kwargs = mock_init.call_args[1]
                self.assertEqual(call_kwargs["labels"], ["urgent", "patient-no-show", "follow-up"])

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_default_labels_when_secret_missing(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that default labels are used when LABELS secret is not configured."""
        # Setup without LABELS secret
        self.protocol.secrets = {"TEAM_NAME": "Admin"}
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.return_value = self.mock_team

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        with patch.object(AddTask, "__init__", return_value=None) as mock_init:
            with patch.object(AddTask, "apply", return_value=Mock()):
                effects = self.protocol.compute()

                # Verify default labels were used
                mock_init.assert_called_once()
                call_kwargs = mock_init.call_args[1]
                self.assertEqual(call_kwargs["labels"], ["no-show", "reschedule"])

    @patch("appointment_no_show_task.protocols.no_show_creates_task.Team")
    @patch("appointment_no_show_task.protocols.no_show_creates_task.Appointment")
    def test_labels_with_whitespace_handling(
        self, mock_appointment_class, mock_team_class
    ):
        """Test that labels with extra whitespace are trimmed correctly."""
        # Setup with labels containing whitespace
        self.protocol.secrets = {
            "TEAM_NAME": "Admin",
            "LABELS": " urgent , no-show  ,  follow-up "
        }
        mock_appointment_class.objects.get.return_value = self.mock_appointment
        mock_team_class.objects.get.return_value = self.mock_team

        # Set up protocol target
        self.protocol.target = "appointment-456"

        # Execute
        with patch.object(AddTask, "__init__", return_value=None) as mock_init:
            with patch.object(AddTask, "apply", return_value=Mock()):
                effects = self.protocol.compute()

                # Verify labels were trimmed
                mock_init.assert_called_once()
                call_kwargs = mock_init.call_args[1]
                self.assertEqual(call_kwargs["labels"], ["urgent", "no-show", "follow-up"])


if __name__ == "__main__":
    unittest.main()
