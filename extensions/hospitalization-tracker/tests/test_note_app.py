"""Tests for HospitalizationTrackerApp note application."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from hospitalization_tracker.applications.note_app import HospitalizationTrackerApp


def test_note_app_identifier() -> None:
    """IDENTIFIER is set to the expected plugin namespace value."""
    assert HospitalizationTrackerApp.IDENTIFIER == "hospitalization_tracker__add"


def test_note_app_name() -> None:
    """NAME is set to 'Add Hospitalization'."""
    assert HospitalizationTrackerApp.NAME == "Add Hospitalization"


@patch("hospitalization_tracker.applications.note_app.Note.objects")
def test_on_open_returns_launch_modal_effect(mock_note_objects: MagicMock) -> None:
    """on_open() returns a LaunchModalEffect with NOTE target type."""
    mock_note = MagicMock()
    mock_note.id = "note-uuid-abc123"
    mock_note_objects.get.return_value = mock_note

    mock_event = MagicMock()
    mock_event.context = {
        "patient": {"id": "patient-uuid-xyz"},
        "note_id": 42,
    }

    app = HospitalizationTrackerApp(event=mock_event)
    effect = app.on_open()

    # Verify it's a valid effect (LaunchModalEffect.apply() returns an Effect)
    assert effect is not None


@patch("hospitalization_tracker.applications.note_app.Note.objects")
def test_on_open_uses_correct_url_params(mock_note_objects: MagicMock) -> None:
    """on_open() constructs the URL with patient_id and note_id query params."""
    mock_note = MagicMock()
    mock_note.id = "note-uuid-abc123"
    mock_note_objects.get.return_value = mock_note

    mock_event = MagicMock()
    mock_event.context = {
        "patient": {"id": "patient-uuid-xyz"},
        "note_id": 42,
    }

    captured_urls: list[str] = []

    original_init = LaunchModalEffect.__init__

    def capture_init(self: LaunchModalEffect, **kwargs: object) -> None:
        captured_urls.append(str(kwargs.get("url", "")))
        original_init(self, **kwargs)

    with patch.object(LaunchModalEffect, "__init__", capture_init):
        app = HospitalizationTrackerApp(event=mock_event)
        app.on_open()

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "patient_id=patient-uuid-xyz" in url
    assert "note_id=note-uuid-abc123" in url
    assert "/plugin-io/api/hospitalization_tracker/app/form" in url


@patch("hospitalization_tracker.applications.note_app.Note.objects")
def test_on_open_uses_note_target_type(mock_note_objects: MagicMock) -> None:
    """on_open() uses LaunchModalEffect.TargetType.NOTE."""
    mock_note = MagicMock()
    mock_note.id = "note-uuid-def456"
    mock_note_objects.get.return_value = mock_note

    mock_event = MagicMock()
    mock_event.context = {
        "patient": {"id": "patient-uuid-abc"},
        "note_id": 7,
    }

    captured_targets: list[object] = []

    original_init = LaunchModalEffect.__init__

    def capture_init(self: LaunchModalEffect, **kwargs: object) -> None:
        captured_targets.append(kwargs.get("target"))
        original_init(self, **kwargs)

    with patch.object(LaunchModalEffect, "__init__", capture_init):
        app = HospitalizationTrackerApp(event=mock_event)
        app.on_open()

    assert len(captured_targets) == 1
    assert captured_targets[0] == LaunchModalEffect.TargetType.NOTE


@patch("hospitalization_tracker.applications.note_app.Note.objects")
def test_on_open_fetches_note_by_dbid(mock_note_objects: MagicMock) -> None:
    """on_open() fetches the Note using dbid from context."""
    mock_note = MagicMock()
    mock_note.id = "note-uuid-ghi789"
    mock_note_objects.get.return_value = mock_note

    mock_event = MagicMock()
    mock_event.context = {
        "patient": {"id": "patient-uuid-jkl"},
        "note_id": 99,
    }

    app = HospitalizationTrackerApp(event=mock_event)
    app.on_open()

    mock_note_objects.get.assert_called_once_with(dbid=99)
