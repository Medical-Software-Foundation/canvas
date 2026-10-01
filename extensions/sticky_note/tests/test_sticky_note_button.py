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
        assert button.BUTTON_TITLE == "⛔ Sticky Note"

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
        assert button.BUTTON_BACKGROUND_COLOR == "#c7c7c7"


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


def _mock_note_contents(mock_model, contents):
    """Wire the StickyNote query chain in _has_content to return ``contents``."""
    chain = mock_model.objects.filter.return_value.filter.return_value
    chain.values_list.return_value = contents


def test_has_content_true_when_note_has_text():
    """A visible note with non-whitespace text counts as content."""
    button = _make_button()
    with patch("sticky_note.protocols.sticky_note_button.StickyNote") as mock_model:
        _mock_note_contents(mock_model, ["", "  call the pharmacy  "])
        assert button._has_content() is True


def test_has_content_false_when_notes_blank():
    """Empty or whitespace-only notes do not count as content."""
    button = _make_button()
    with patch("sticky_note.protocols.sticky_note_button.StickyNote") as mock_model:
        _mock_note_contents(mock_model, ["", "   "])
        assert button._has_content() is False


def test_has_content_false_when_no_notes():
    """A patient with no sticky notes has no content."""
    button = _make_button()
    with patch("sticky_note.protocols.sticky_note_button.StickyNote") as mock_model:
        _mock_note_contents(mock_model, [])
        assert button._has_content() is False


def test_compute_filled_shows_memo_on_yellow():
    """A filled note renders the memo glyph on the filled (yellow) background."""
    from sticky_note.protocols.sticky_note_button import StickyNoteButton

    button = _make_button()
    button.event.name = "SHOW_CHART_PATIENT_HEADER_BUTTON"
    with patch.object(button, "_has_content", return_value=True):
        effects = button.compute()

    assert button.BUTTON_TITLE == "📝 Sticky Note"
    assert button.BUTTON_BACKGROUND_COLOR == StickyNoteButton.FILLED_BACKGROUND_COLOR
    assert len(effects) == 1


def test_compute_empty_shows_no_entry_on_gray():
    """An empty note renders the no-entry glyph on the empty (gray) background."""
    from sticky_note.protocols.sticky_note_button import StickyNoteButton

    button = _make_button()
    button.event.name = "SHOW_CHART_PATIENT_HEADER_BUTTON"
    with patch.object(button, "_has_content", return_value=False):
        effects = button.compute()

    assert button.BUTTON_TITLE == "⛔ Sticky Note"
    assert button.BUTTON_BACKGROUND_COLOR == StickyNoteButton.EMPTY_BACKGROUND_COLOR
    assert len(effects) == 1


def test_compute_click_event_opens_modal():
    """The click event opens the sticky note modal."""
    button = _make_button()
    button.event.name = "ACTION_BUTTON_CLICKED"
    button.event.context = {"key": "STICKY_NOTE", "user": {"id": "staff-uuid-456"}}
    with (
        patch.object(button, "_has_content", return_value=True),
        patch(
            "sticky_note.protocols.sticky_note_button.render_to_string",
            return_value="<html></html>",
        ),
    ):
        effects = button.compute()

    assert len(effects) == 1
