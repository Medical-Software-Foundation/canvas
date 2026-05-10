"""Phase A tests for PrintNutritionNoteButton gating + URL shape."""

from unittest.mock import MagicMock, patch

from canvas_sdk.handlers.action_button import ActionButton

from nutrition_charting.protocols.print_button import PrintNutritionNoteButton


def _mock_event(*, note_id: int | None = 11) -> MagicMock:
    event = MagicMock()
    event.context = {"note_id": note_id}
    event.target.id = "patient-abc"
    return event


def _mock_note(note_type_name: str) -> MagicMock:
    note = MagicMock()
    note.id = "note-uuid-1"
    note.note_type_version.name = note_type_name
    return note


def test_button_inherits_action_button_and_is_in_note_header() -> None:
    assert issubclass(PrintNutritionNoteButton, ActionButton)
    assert PrintNutritionNoteButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER
    assert PrintNutritionNoteButton.BUTTON_TITLE == "Print Nutrition Note"
    assert PrintNutritionNoteButton.BUTTON_KEY == "PRINT_NUTRITION_NOTE"


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_true_on_nutrition_note(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note("Nutrition Visit")

    button = PrintNutritionNoteButton(event=_mock_event())

    assert button.visible() is True


@patch("nutrition_charting.applications.nutrition_charting_app.Note")
def test_visible_false_on_non_nutrition_note(mock_note_cls: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = _mock_note("Office Visit")

    button = PrintNutritionNoteButton(event=_mock_event())

    assert button.visible() is False


@patch("nutrition_charting.protocols.print_button.Note")
def test_handle_resolves_note_dbid_to_uuids_for_print_url(
    mock_note_cls: MagicMock,
) -> None:
    """The note_id from event context is a small-int dbid. The print API
    queries Note + Patient by UUID, so the button must resolve note.id and
    note.patient.id before composing the URL — otherwise the dbid hits a
    UUIDField validator downstream and the print modal renders an error."""
    note = MagicMock()
    note.id = "note-uuid-xyz"
    patient = MagicMock()
    patient.id = "patient-uuid-abc"
    note.patient = patient
    mock_note_cls.objects.select_related.return_value.get.return_value = note

    event = _mock_event(note_id=11)
    button = PrintNutritionNoteButton(event=event)

    effects = button.handle()

    assert len(effects) == 1
    payload = effects[0].payload
    assert "/plugin-io/api/nutrition_charting/print/" in payload
    assert "patient_id=patient-uuid-abc" in payload
    assert "note_id=note-uuid-xyz" in payload
    # Confirm the lookup ran by dbid (so we know we're resolving, not echoing).
    mock_note_cls.objects.select_related.assert_called_once_with("patient")
    mock_note_cls.objects.select_related.return_value.get.assert_called_once_with(dbid=11)


@patch("nutrition_charting.protocols.print_button.Note")
def test_handle_emits_url_with_blank_ids_when_note_missing(
    mock_note_cls: MagicMock,
) -> None:
    """If the note isn't found we still launch the modal — the print API
    will render its own error page rather than letting the button silently
    do nothing."""
    class _DNE(Exception):
        pass

    mock_note_cls.DoesNotExist = _DNE
    mock_note_cls.objects.select_related.return_value.get.side_effect = _DNE()

    button = PrintNutritionNoteButton(event=_mock_event(note_id=11))
    effects = button.handle()

    assert len(effects) == 1
    payload = effects[0].payload
    assert "patient_id=&note_id=" in payload
