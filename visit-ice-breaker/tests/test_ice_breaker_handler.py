from datetime import date
from unittest.mock import MagicMock, call, patch

from canvas_sdk.effects import EffectType

from visit_ice_breaker.handlers.ice_breaker_handler import IceBreakerHandler
from visit_ice_breaker.question_bank import Question
from visit_ice_breaker.structures.age_group import AgeGroup


@patch("visit_ice_breaker.handlers.ice_breaker_handler.QuestionTracker")
@patch("visit_ice_breaker.handlers.ice_breaker_handler.AgeGroup")
@patch("visit_ice_breaker.handlers.ice_breaker_handler.Patient")
@patch("visit_ice_breaker.handlers.ice_breaker_handler.Note")
def test_compute(
    mock_note_cls: MagicMock,
    mock_patient_cls: MagicMock,
    mock_age_group_cls: MagicMock,
    mock_tracker_cls: MagicMock,
) -> None:
    def reset_mocks() -> None:
        mock_note_cls.reset_mock()
        mock_patient_cls.reset_mock()
        mock_age_group_cls.reset_mock()
        mock_tracker_cls.reset_mock()

    # skips non-NEW state
    mock_event: MagicMock = MagicMock()
    mock_event.context = {"state": "SIGNED"}

    tested: IceBreakerHandler = IceBreakerHandler(event=mock_event)
    result = tested.compute()
    assert result == []
    assert mock_note_cls.mock_calls == []
    reset_mocks()

    # skips non-office-visit note type
    mock_note: MagicMock = MagicMock()
    mock_note.note_type_version.name = "Progress note"
    mock_note_cls.objects.select_related.return_value.get.side_effect = [mock_note]

    mock_event = MagicMock()
    mock_event.context = {"state": "NEW", "note_id": 42}

    tested = IceBreakerHandler(event=mock_event)
    result = tested.compute()
    assert result == []
    reset_mocks()

    # creates instruct command for new office visit
    mock_note = MagicMock()
    mock_note.note_type_version.name = "Office visit"
    mock_note.id = "note-uuid-123"
    mock_note_cls.objects.select_related.return_value.get.side_effect = [mock_note]

    mock_patient: MagicMock = MagicMock()
    mock_patient.birth_date = date(1990, 5, 10)
    mock_patient_cls.objects.get.side_effect = [mock_patient]

    mock_age_group_cls.from_birth_date.side_effect = [AgeGroup.ADULTS]

    question: Question = Question("Travel & Adventure", "Best trip ever?")
    mock_tracker_cls.get_or_select_question.side_effect = [question]

    mock_event = MagicMock()
    mock_event.context = {"state": "NEW", "note_id": 99, "patient_id": "patient-789"}

    tested = IceBreakerHandler(event=mock_event)
    result = tested.compute()
    assert len(result) == 1
    assert result[0].type == EffectType.ORIGINATE_INSTRUCT_COMMAND

    calls = [call.objects.select_related("note_type_version"), call.objects.select_related().get(id=99)]
    assert mock_note_cls.mock_calls == calls
    calls = [call.objects.get(id="patient-789")]
    assert mock_patient_cls.mock_calls == calls
    calls = [call.from_birth_date(date(1990, 5, 10))]
    assert mock_age_group_cls.mock_calls == calls
    calls = [
        call.get_or_select_question(
            note_id="note-uuid-123",
            patient_id="patient-789",
            age_group=AgeGroup.ADULTS,
        )
    ]
    assert mock_tracker_cls.mock_calls == calls
    reset_mocks()
