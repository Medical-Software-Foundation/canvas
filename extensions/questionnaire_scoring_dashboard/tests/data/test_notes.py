from unittest.mock import MagicMock, patch

from questionnaire_scoring_dashboard.data.notes import fetch_open_note_rows


@patch("questionnaire_scoring_dashboard.data.notes.CurrentNoteStateEvent")
@patch("questionnaire_scoring_dashboard.data.notes.Note")
def test_fetch_open_note_rows_returns_editable_for_patient(mock_note, mock_state):
    note = MagicMock()
    note.id = "ext-1"
    note.dbid = 1
    note.datetime_of_service.isoformat.return_value = "2026-02-14T09:00:00+00:00"
    note.title = "Office Visit"
    mock_note.objects.filter.return_value = [note]
    mock_state.objects.filter.return_value.values_list.return_value = [1]

    rows = fetch_open_note_rows("patient-1")
    assert rows == [
        {"id": "ext-1", "dos": "2026-02-14T09:00:00+00:00", "title": "Office Visit"}
    ]
    mock_note.objects.filter.assert_called_once_with(
        patient__id="patient-1", dbid__in=[1]
    )


@patch("questionnaire_scoring_dashboard.data.notes.CurrentNoteStateEvent")
@patch("questionnaire_scoring_dashboard.data.notes.Note")
def test_fetch_open_note_rows_handles_missing_dos(mock_note, mock_state):
    note = MagicMock()
    note.id = "ext-2"
    note.datetime_of_service = None
    note.title = ""
    mock_note.objects.filter.return_value = [note]
    mock_state.objects.filter.return_value.values_list.return_value = [2]

    rows = fetch_open_note_rows("patient-1")
    assert rows == [{"id": "ext-2", "dos": "", "title": ""}]
