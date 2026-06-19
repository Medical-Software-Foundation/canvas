from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from questionnaire_scoring_dashboard.data.observations import fetch_survey_rows


@patch("questionnaire_scoring_dashboard.data.observations.Note")
@patch("questionnaire_scoring_dashboard.data.observations.Observation")
def test_fetch_survey_rows_filters_and_attaches_note_dos(mock_obs, mock_note):
    qs = MagicMock()
    mock_obs.objects.for_patient.return_value = qs
    qs.filter.return_value = qs
    qs.exclude.return_value = qs
    qs.values.return_value = [
        {"note_id": 1, "value": "16", "effective_datetime": None, "created": None,
         "name": "PHQ-9", "codings__code": "44261-6"}
    ]
    dos = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    mock_note.objects.filter.return_value.values_list.return_value = [(1, dos)]

    rows = fetch_survey_rows("patient-123")

    mock_obs.objects.for_patient.assert_called_once_with("patient-123")
    qs.filter.assert_called_once_with(category="survey")
    qs.exclude.assert_called_once_with(entered_in_error__isnull=False)
    # The coding code is pulled in the same query (one LEFT JOIN, no N+1).
    qs.values.assert_called_once_with(
        "note_id", "value", "effective_datetime", "created", "name", "codings__code"
    )
    mock_note.objects.filter.assert_called_once_with(dbid__in={1})
    assert rows[0]["note_dos"] == dos.isoformat()
    assert rows[0]["code"] == "44261-6"


@patch("questionnaire_scoring_dashboard.data.observations.Note")
@patch("questionnaire_scoring_dashboard.data.observations.Observation")
def test_fetch_survey_rows_handles_no_note(mock_obs, mock_note):
    qs = MagicMock()
    mock_obs.objects.for_patient.return_value = qs
    qs.filter.return_value = qs
    qs.exclude.return_value = qs
    qs.values.return_value = [
        {"note_id": None, "value": "5", "effective_datetime": None, "created": None,
         "name": "AUDIT", "codings__code": None}
    ]

    rows = fetch_survey_rows("p1")
    assert rows[0]["note_dos"] is None
    assert rows[0]["code"] is None
    mock_note.objects.filter.assert_not_called()
