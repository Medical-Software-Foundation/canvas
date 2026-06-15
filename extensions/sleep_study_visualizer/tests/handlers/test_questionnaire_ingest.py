"""Tests for SleepStudyQuestionnaireHandler (QUESTIONNAIRE_COMMAND__POST_COMMIT)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sleep_study_visualizer.handlers.questionnaire_ingest import (
    SleepStudyQuestionnaireHandler,
    _resolve_sing_option_code,
    _to_date,
    _to_decimal,
    _to_int,
)


def _make_event(fields: dict, context_extra: dict | None = None):
    event = MagicMock()
    event.context = {"fields": fields, **(context_extra or {})}
    return event


def _make_handler(fields: dict, context_extra: dict | None = None):
    return SleepStudyQuestionnaireHandler(_make_event(fields, context_extra))


def _sleep_study_payload(
    study_date: str = "2026-05-20",
    ahi: str = "18",
    rdi: str = "22",
    odi: str = "14",
    severity_option_pk: int | None = 102,
    epworth: str = "12",
    note_uuid: str = "note-1",
) -> dict:
    """Build a realistic event payload mimicking a Sleep Study Result commit."""
    severity_options = [
        {"pk": 100, "code": "SLEEP-STUDY-SEVERITY-NORMAL", "label": "Normal"},
        {"pk": 101, "code": "SLEEP-STUDY-SEVERITY-MILD", "label": "Mild"},
        {"pk": 102, "code": "SLEEP-STUDY-SEVERITY-MODERATE", "label": "Moderate"},
        {"pk": 103, "code": "SLEEP-STUDY-SEVERITY-SEVERE", "label": "Severe"},
    ]
    questions = [
        {"pk": 1, "name": "question-1", "type": "TXT",
         "coding": {"code": "SLEEP-STUDY-DATE", "system": "INTERNAL"}, "options": []},
        {"pk": 2, "name": "question-2", "type": "TXT",
         "coding": {"code": "SLEEP-STUDY-AHI", "system": "INTERNAL"}, "options": []},
        {"pk": 3, "name": "question-3", "type": "TXT",
         "coding": {"code": "SLEEP-STUDY-RDI", "system": "INTERNAL"}, "options": []},
        {"pk": 4, "name": "question-4", "type": "TXT",
         "coding": {"code": "SLEEP-STUDY-ODI", "system": "INTERNAL"}, "options": []},
        {"pk": 5, "name": "question-5", "type": "SING",
         "coding": {"code": "SLEEP-STUDY-SEVERITY", "system": "INTERNAL"},
         "options": severity_options},
        {"pk": 6, "name": "question-6", "type": "TXT",
         "coding": {"code": "SLEEP-STUDY-EPWORTH", "system": "INTERNAL"}, "options": []},
    ]
    return {
        "questionnaire": {"text": "Sleep Study Result", "extra": {"questions": questions}},
        "question-1": study_date,
        "question-2": ahi,
        "question-3": rdi,
        "question-4": odi,
        "question-5": severity_option_pk,
        "question-6": epworth,
        "note": {"uuid": note_uuid},
    }


class TestParsers:
    def test_decimal_parses(self):
        assert _to_decimal("14.5") == Decimal("14.5")

    def test_decimal_empty(self):
        assert _to_decimal("") is None

    def test_decimal_garbage(self):
        assert _to_decimal("not a number") is None

    def test_int_truncates(self):
        assert _to_int("12.7") == 12

    def test_date_iso(self):
        assert _to_date("2026-04-12") == date(2026, 4, 12)

    def test_date_us(self):
        assert _to_date("11/05/2023") == date(2023, 11, 5)

    def test_date_short_year(self):
        assert _to_date("11/05/23") == date(2023, 11, 5)

    def test_date_garbage(self):
        assert _to_date("not a date") is None


class TestResolveSingOptionCode:
    def test_resolves_by_pk(self):
        options = [
            {"pk": 1, "code": "A", "label": "A"},
            {"pk": 2, "code": "B", "label": "B"},
        ]
        assert _resolve_sing_option_code(options, 2) == "B"

    def test_returns_none_for_missing_pk(self):
        options = [{"pk": 1, "code": "A", "label": "A"}]
        assert _resolve_sing_option_code(options, 99) is None

    def test_returns_none_for_empty_selection(self):
        assert _resolve_sing_option_code([], "") is None
        assert _resolve_sing_option_code([], None) is None

    def test_returns_none_for_non_numeric_pk(self):
        assert _resolve_sing_option_code([{"pk": 1, "code": "A"}], "abc") is None


class TestHandler:
    def test_skips_unrelated_questionnaire(self):
        handler = _make_handler({
            "questionnaire": {
                "extra": {
                    "questions": [
                        {"pk": 1, "name": "question-1", "type": "TXT",
                         "coding": {"code": "TOBACCO-STATUS"}, "options": []}
                    ]
                }
            },
            "question-1": "Never",
            "note": {"uuid": "note-1"},
        })
        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            assert handler.compute() == []
            mock_ssr.objects.create.assert_not_called()

    def test_persists_on_full_payload(self):
        payload = _sleep_study_payload()
        handler = _make_handler(payload)
        note = MagicMock()
        note.patient_id = 7
        custom_patient = MagicMock()
        custom_patient.dbid = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = note
            mock_cp.filter.return_value.first.return_value = custom_patient
            mock_ssr.objects.filter.return_value.first.return_value = None  # not duplicate

            assert handler.compute() == []

            mock_ssr.objects.create.assert_called_once()
            kwargs = mock_ssr.objects.create.call_args.kwargs
            assert kwargs["patient"] is custom_patient
            assert kwargs["study_date"] == date(2026, 5, 20)
            assert kwargs["ahi"] == Decimal("18")
            assert kwargs["rdi"] == Decimal("22")
            assert kwargs["odi"] == Decimal("14")
            assert kwargs["severity"] == "Moderate"
            assert kwargs["epworth_score"] == 12

    def test_skips_when_date_unparseable(self):
        payload = _sleep_study_payload(study_date="garbage")
        handler = _make_handler(payload)

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            assert handler.compute() == []
            mock_ssr.objects.create.assert_not_called()

    def test_skips_when_no_patient_anywhere(self):
        payload = _sleep_study_payload(note_uuid="")
        payload["note"] = {}
        handler = _make_handler(payload)

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = None
            mock_cp.filter.return_value.first.return_value = None
            assert handler.compute() == []
            mock_ssr.objects.create.assert_not_called()

    def test_idempotent_when_already_exists(self):
        payload = _sleep_study_payload()
        handler = _make_handler(payload)
        note = MagicMock()
        note.patient_id = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = note
            patient = MagicMock()
            patient.dbid = 7
            mock_cp.filter.return_value.first.return_value = patient
            # Simulate existing row for this patient+date
            mock_ssr.objects.filter.return_value.first.return_value = MagicMock()

            assert handler.compute() == []
            mock_ssr.objects.create.assert_not_called()

    def test_resolves_patient_via_context_patient_id(self):
        # Path 1: event.context["patient"]["id"] -> CustomPatient by external id.
        payload = _sleep_study_payload(note_uuid="")
        handler = _make_handler(payload, context_extra={"patient": {"id": "ext-1"}})
        patient = MagicMock()
        patient.dbid = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_cp.filter.return_value.first.return_value = patient
            mock_ssr.objects.filter.return_value.first.return_value = None

            assert handler.compute() == []
            mock_ssr.objects.create.assert_called_once()
            assert mock_ssr.objects.create.call_args.kwargs["patient"] is patient

    def test_resolves_patient_via_command_walkback(self):
        # Path 3: no context patient, no note uuid -> walk command -> Note -> patient.
        payload = _sleep_study_payload(note_uuid="")
        handler = _make_handler(payload)
        note = MagicMock()
        note.patient_id = 7
        patient = MagicMock()
        patient.dbid = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = note
            mock_cp.filter.return_value.first.return_value = patient
            mock_ssr.objects.filter.return_value.first.return_value = None

            assert handler.compute() == []
            mock_ssr.objects.create.assert_called_once()

    def test_skips_when_custom_patient_row_missing(self):
        # patient_dbid resolves but no CustomPatient row exists for it.
        payload = _sleep_study_payload()
        handler = _make_handler(payload)
        note = MagicMock()
        note.patient_id = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = note
            mock_cp.filter.return_value.first.return_value = None

            assert handler.compute() == []
            mock_ssr.objects.create.assert_not_called()

    def test_accepts_us_date_format(self):
        payload = _sleep_study_payload(study_date="11/05/2023")
        handler = _make_handler(payload)
        note = MagicMock()
        note.patient_id = 7
        patient = MagicMock()
        patient.dbid = 7

        with patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.Note.objects"
        ) as mock_note, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.CustomPatient.objects"
        ) as mock_cp, patch(
            "sleep_study_visualizer.handlers.questionnaire_ingest.SleepStudyResult"
        ) as mock_ssr:
            mock_note.filter.return_value.first.return_value = note
            mock_cp.filter.return_value.first.return_value = patient
            mock_ssr.objects.filter.return_value.first.return_value = None

            assert handler.compute() == []

            kwargs = mock_ssr.objects.create.call_args.kwargs
            assert kwargs["study_date"] == date(2023, 11, 5)
