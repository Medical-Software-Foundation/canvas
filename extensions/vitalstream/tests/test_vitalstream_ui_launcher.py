import json
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import NoteStates

from vitalstream.applications.vitalstream_ui import VitalstreamUILauncher


class TestVitalstreamUILauncher:
    """Tests for the VitalstreamUILauncher class."""

    def create_launcher_instance(self, context: dict) -> VitalstreamUILauncher:
        """Helper to create a VitalstreamUILauncher instance with mocked event."""
        launcher = VitalstreamUILauncher.__new__(VitalstreamUILauncher)
        launcher.event = Mock()
        launcher.event.context = context
        return launcher

    def test_button_attributes(self) -> None:
        """Test that button attributes are configured correctly."""
        assert VitalstreamUILauncher.BUTTON_TITLE == "Record with VitalStream"
        assert VitalstreamUILauncher.BUTTON_KEY == "LAUNCH_VITALSTREAM"
        assert VitalstreamUILauncher.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER

    @patch("vitalstream.applications.vitalstream_ui.CurrentNoteStateEvent")
    def test_visible_returns_false_when_note_is_locked(self, mock_note_state_event) -> None:
        """Test that visible returns False when the note is locked."""
        mock_state = Mock()
        mock_state.state = NoteStates.LOCKED
        mock_note_state_event.objects.get.return_value = mock_state

        launcher = self.create_launcher_instance(context={"note_id": "note-123"})

        result = launcher.visible()

        assert result is False
        mock_note_state_event.objects.get.assert_called_once_with(note__dbid="note-123")

    @patch("vitalstream.applications.vitalstream_ui.CurrentNoteStateEvent")
    def test_visible_returns_true_when_note_is_not_locked(self, mock_note_state_event) -> None:
        """Test that visible returns True when the note is not locked."""
        mock_state = Mock()
        mock_state.state = NoteStates.NEW
        mock_note_state_event.objects.get.return_value = mock_state

        launcher = self.create_launcher_instance(context={"note_id": "note-123"})

        result = launcher.visible()

        assert result is True

    def test_handle_raises_error_when_user_is_not_staff(self) -> None:
        """Test that handle raises RuntimeError when user is not Staff."""
        launcher = self.create_launcher_instance(
            context={
                "note_id": "note-123",
                "user": {"type": "Patient", "id": "patient-456"},
            }
        )

        with pytest.raises(RuntimeError, match="Launching user must be Staff!"):
            launcher.handle()

    def test_handle_raises_error_when_user_is_missing(self) -> None:
        """Test that handle raises RuntimeError when user is missing from context."""
        launcher = self.create_launcher_instance(context={"note_id": "note-123"})

        with pytest.raises(RuntimeError, match="Launching user must be Staff!"):
            launcher.handle()

    @patch("vitalstream.applications.vitalstream_ui.get_cache")
    @patch("vitalstream.applications.vitalstream_ui.uuid4")
    def test_handle_returns_launch_modal_effect(self, mock_uuid4, mock_get_cache) -> None:
        """Test that handle returns a LaunchModalEffect with correct URL."""
        mock_uuid4.return_value = "test-session-uuid"
        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        launcher = self.create_launcher_instance(
            context={
                "note_id": "note-123",
                "user": {"type": "Staff", "id": "staff-456"},
            }
        )

        effects = launcher.handle()

        assert len(effects) == 1
        effect = effects[0]
        payload = json.loads(effect.payload)["data"]
        assert payload["url"] == "/plugin-io/api/vitalstream/vitalstream-ui/sessions/test-session-uuid/"
        assert payload["target"] == "right_chart_pane"

    @patch("vitalstream.applications.vitalstream_ui.get_cache")
    @patch("vitalstream.applications.vitalstream_ui.uuid4")
    def test_get_new_session_id_generates_and_caches_session(self, mock_uuid4, mock_get_cache) -> None:
        """Test that get_new_session_id generates a session ID and caches it."""
        mock_uuid4.return_value = "generated-uuid"
        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        launcher = self.create_launcher_instance(context={})

        result = launcher.get_new_session_id("note-123", "staff-456")

        assert result == "generated-uuid"
        mock_cache.set.assert_called_once_with(
            "session_id:generated-uuid",
            {"note_id": "note-123", "staff_id": "staff-456"},
            timeout_seconds=60 * 60 * 24 * 2,
        )

    @patch("vitalstream.applications.vitalstream_ui.get_cache")
    @patch("vitalstream.applications.vitalstream_ui.uuid4")
    def test_get_new_session_id_regenerates_on_collision(self, mock_uuid4, mock_get_cache) -> None:
        """Test that get_new_session_id regenerates UUID if it already exists."""
        mock_uuid4.side_effect = ["existing-uuid", "new-uuid"]
        mock_cache = Mock()
        # First UUID exists, second doesn't
        mock_cache.get.side_effect = [{"existing": "session"}, None]
        mock_get_cache.return_value = mock_cache

        launcher = self.create_launcher_instance(context={})

        result = launcher.get_new_session_id("note-123", "staff-456")

        assert result == "new-uuid"
        assert mock_uuid4.call_count == 2

    @patch("vitalstream.applications.vitalstream_ui.get_cache")
    @patch("vitalstream.applications.vitalstream_ui.uuid4")
    def test_get_new_session_id_raises_after_max_attempts(self, mock_uuid4, mock_get_cache) -> None:
        """Test that get_new_session_id raises RuntimeError after 10 failed attempts."""
        mock_uuid4.return_value = "always-existing-uuid"
        mock_cache = Mock()
        mock_cache.get.return_value = {"existing": "session"}
        mock_get_cache.return_value = mock_cache

        launcher = self.create_launcher_instance(context={})

        with pytest.raises(RuntimeError, match="Could not generate a session identifier"):
            launcher.get_new_session_id("note-123", "staff-456")

        # Should have tried 11 times (initial + 10 retries)
        assert mock_uuid4.call_count == 11
