"""Tests for medication_change_broadcast protocol."""

import pytest
from unittest.mock import MagicMock, patch, call

from high_risk_medications.protocols.medication_change_broadcast import MedicationChangeBroadcast


class TestMedicationChangeBroadcast:
    """Test suite for the medication change broadcast protocol."""

    def test_broadcasts_on_medication_change(self, mock_event):
        """Test that broadcast is sent when medication changes."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_123"}}

        # Execute
        handler = MedicationChangeBroadcast(event=mock_event)
        effects = handler.compute()

        # Verify output
        assert len(effects) == 1
        effect = effects[0]
        assert effect is not None

    def test_sanitizes_channel_name_with_dashes(self, mock_event):
        """Test that channel names with dashes are sanitized to underscores."""
        # Setup - real patient IDs have dashes
        mock_event.context = {"patient": {"id": "17f4e5fd-3d28-4955-bdc3-4f4ba5c1f35c"}}

        # Execute
        with patch("high_risk_medications.protocols.medication_change_broadcast.Broadcast") as mock_broadcast:
            mock_broadcast_instance = MagicMock()
            mock_broadcast.return_value = mock_broadcast_instance
            mock_broadcast_instance.apply.return_value = MagicMock()

            handler = MedicationChangeBroadcast(event=mock_event)
            effects = handler.compute()

            # Verify channel was sanitized (dashes replaced with underscores)
            assert mock_broadcast.called
            call_args = mock_broadcast.call_args
            assert call_args[1]["channel"] == "17f4e5fd_3d28_4955_bdc3_4f4ba5c1f35c"

    def test_handles_missing_patient_context(self, mock_event):
        """Test graceful handling when patient context is missing."""
        # Setup
        mock_event.context = {}

        # Execute
        handler = MedicationChangeBroadcast(event=mock_event)
        effects = handler.compute()

        # Verify output - should return empty list
        assert effects == []

    def test_handles_missing_patient_id(self, mock_event):
        """Test graceful handling when patient ID is None."""
        # Setup
        mock_event.context = {"patient": {"id": None}}

        # Execute
        handler = MedicationChangeBroadcast(event=mock_event)
        effects = handler.compute()

        # Verify output - should return empty list
        assert effects == []

    def test_handles_missing_patient_key(self, mock_event):
        """Test graceful handling when patient key is missing from context."""
        # Setup
        mock_event.context = {"user": {"id": "staff_123"}}

        # Execute
        handler = MedicationChangeBroadcast(event=mock_event)
        effects = handler.compute()

        # Verify output - should return empty list
        assert effects == []

    def test_broadcast_message_format(self, mock_event):
        """Test that broadcast message has correct event format."""
        # Setup
        mock_event.context = {"patient": {"id": "patient_222"}}

        # Execute
        with patch("high_risk_medications.protocols.medication_change_broadcast.Broadcast") as mock_broadcast:
            mock_broadcast_instance = MagicMock()
            mock_broadcast.return_value = mock_broadcast_instance
            mock_broadcast_instance.apply.return_value = MagicMock()

            handler = MedicationChangeBroadcast(event=mock_event)
            effects = handler.compute()

            # Verify message format
            assert mock_broadcast.called
            call_args = mock_broadcast.call_args
            assert call_args[1]["message"] == {"event": "medication_changed"}
            assert call_args[1]["channel"] == "patient_222"

    def test_responds_to_prescribe_events(self):
        """Test that handler responds to prescription events."""
        # Verify RESPONDS_TO includes prescription events
        from canvas_sdk.events import EventType

        responds_to = MedicationChangeBroadcast.RESPONDS_TO

        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_medication_statement_events(self):
        """Test that handler responds to medication statement events."""
        from canvas_sdk.events import EventType

        responds_to = MedicationChangeBroadcast.RESPONDS_TO

        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_stop_medication_events(self):
        """Test that handler responds to stop medication events."""
        from canvas_sdk.events import EventType

        responds_to = MedicationChangeBroadcast.RESPONDS_TO

        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_responds_to_adjust_prescription_events(self):
        """Test that handler responds to adjust prescription events."""
        from canvas_sdk.events import EventType

        responds_to = MedicationChangeBroadcast.RESPONDS_TO

        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT) in responds_to
        assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ENTER_IN_ERROR) in responds_to

    def test_handles_empty_patient_id_string(self, mock_event):
        """Test handling of empty string patient ID."""
        # Setup
        mock_event.context = {"patient": {"id": ""}}

        # Execute
        handler = MedicationChangeBroadcast(event=mock_event)
        effects = handler.compute()

        # Verify output - should return empty list
        assert effects == []

    def test_preserves_alphanumeric_channel_names(self, mock_event):
        """Test that alphanumeric channel names are preserved."""
        # Setup
        mock_event.context = {"patient": {"id": "patient123abc"}}

        # Execute
        with patch("high_risk_medications.protocols.medication_change_broadcast.Broadcast") as mock_broadcast:
            mock_broadcast_instance = MagicMock()
            mock_broadcast.return_value = mock_broadcast_instance
            mock_broadcast_instance.apply.return_value = MagicMock()

            handler = MedicationChangeBroadcast(event=mock_event)
            effects = handler.compute()

            # Verify channel was preserved as-is
            call_args = mock_broadcast.call_args
            assert call_args[1]["channel"] == "patient123abc"
