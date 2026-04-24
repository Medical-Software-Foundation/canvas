from unittest.mock import MagicMock, patch

from canvas_sdk.handlers.action_button import ActionButton


def _make_button(patient_id="patient-uuid-123", staff_id="staff-uuid-456"):
    from sticky_note.protocols.sticky_note_button import StickyNoteButton

    event = MagicMock()
    event.target.id = patient_id
    event.context = {"user": {"id": staff_id}}

    button = StickyNoteButton(event=event)
    return button


class TestStickyNoteButtonConfig:
    def test_button_title(self):
        button = _make_button()
        assert button.BUTTON_TITLE == "Sticky Note"

    def test_button_key(self):
        button = _make_button()
        assert button.BUTTON_KEY == "STICKY_NOTE"

    def test_button_location(self):
        button = _make_button()
        assert (
            button.BUTTON_LOCATION == ActionButton.ButtonLocation.CHART_PATIENT_HEADER
        )

    def test_button_background_color(self):
        button = _make_button()
        assert button.BUTTON_BACKGROUND_COLOR == "#feff86"


class TestStickyNoteButtonHandle:
    @patch("sticky_note.protocols.sticky_note_button.render_to_string")
    def test_handle_returns_modal_effect(self, mock_render):
        mock_render.return_value = "<html>mock</html>"
        button = _make_button()
        effects = button.handle()

        assert len(effects) == 1
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][0] == "templates/sticky_note.html"
        assert call_args[0][1]["patient_id"] == "patient-uuid-123"
        assert call_args[0][1]["staff_id"] == "staff-uuid-456"

    @patch("sticky_note.protocols.sticky_note_button.render_to_string")
    def test_handle_passes_context_ids(self, mock_render):
        mock_render.return_value = "<html></html>"
        button = _make_button(patient_id="p-999", staff_id="s-888")
        button.handle()

        context = mock_render.call_args[0][1]
        assert context["patient_id"] == "p-999"
        assert context["staff_id"] == "s-888"
