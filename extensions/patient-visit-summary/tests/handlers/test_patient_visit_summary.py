from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

import pytest

from patient_visit_summary.handlers.patient_visit_summary import (
    PatientVisitSummaryAPI,
    PatientVisitSummaryButton,
)
from patient_visit_summary.services.note_data_extractor import (
    ASSESSMENT_STATUS_DICT,
    VITALS_ENUM_DICT,
    NoteDataExtractor,
    format_icd10_code,
)

# Aliases for backward-compatibility with tests written against the old monolithic class
CustomerHTMLApi = PatientVisitSummaryAPI
CustomHTMLActionButton = PatientVisitSummaryButton

# Module path for patching NoteDataExtractor internals
_NDE = "patient_visit_summary.services.note_data_extractor"


# --- format_icd10_code ---


class TestFormatIcd10Code:
    def test_empty_string(self):
        assert format_icd10_code("") == ""

    def test_none(self):
        assert format_icd10_code(None) == ""

    def test_three_char_code(self):
        assert format_icd10_code("E11") == "E11"

    def test_long_code_inserts_dot(self):
        assert format_icd10_code("E1165") == "E11.65"

    def test_four_char_code(self):
        assert format_icd10_code("J449") == "J44.9"

    def test_lowercase_uppercased(self):
        assert format_icd10_code("e1165") == "E11.65"

    def test_whitespace_stripped(self):
        assert format_icd10_code("  E1165  ") == "E11.65"


# --- CustomHTMLActionButton ---


class TestCustomHTMLActionButton:
    def test_button_title(self):
        assert CustomHTMLActionButton.BUTTON_TITLE == "Patient Visit Summary"

    def test_button_key(self):
        assert CustomHTMLActionButton.BUTTON_KEY == "PATIENT_VISIT_SUMMARY"

    def test_button_location(self):
        assert CustomHTMLActionButton.BUTTON_LOCATION == CustomHTMLActionButton.ButtonLocation.NOTE_HEADER

    def test_visible_returns_true(self):
        handler = CustomHTMLActionButton.__new__(CustomHTMLActionButton)
        assert handler.visible() is True

    @patch("patient_visit_summary.handlers.patient_visit_summary.LaunchModalEffect")
    @patch("patient_visit_summary.handlers.patient_visit_summary.Note")
    @patch("patient_visit_summary.handlers.patient_visit_summary.log")
    def test_handle_resolves_note_uuid_into_url(self, mock_log, mock_note_cls, mock_modal):
        note = MagicMock()
        note.id = "note-uuid-xyz"
        mock_note_cls.objects.filter.return_value.first.return_value = note
        handler = CustomHTMLActionButton.__new__(CustomHTMLActionButton)
        mock_event = MagicMock()
        mock_event.context = {"note_id": "456"}
        handler.event = mock_event
        handler._target = "patient-123"

        with patch.object(type(handler), "target", new_callable=lambda: property(lambda self: self._target)):
            effects = handler.handle()

        assert len(effects) == 1
        # dbid from the event context is resolved to the external UUID before
        # it reaches the (browser-visible) modal URL.
        mock_note_cls.objects.filter.assert_called_once_with(dbid="456")
        url = mock_modal.call_args.kwargs["url"]
        assert "note_id=note-uuid-xyz" in url
        assert "patient_id=patient-123" in url
        assert "&v=" in url  # cache-busting token on the modal URL

    @patch("patient_visit_summary.handlers.patient_visit_summary.LaunchModalEffect")
    @patch("patient_visit_summary.handlers.patient_visit_summary.Note")
    @patch("patient_visit_summary.handlers.patient_visit_summary.log")
    def test_handle_missing_note_yields_empty_note_id(self, mock_log, mock_note_cls, mock_modal):
        mock_note_cls.objects.filter.return_value.first.return_value = None
        handler = CustomHTMLActionButton.__new__(CustomHTMLActionButton)
        mock_event = MagicMock()
        mock_event.context = {"note_id": "456"}
        handler.event = mock_event
        handler._target = "patient-123"

        with patch.object(type(handler), "target", new_callable=lambda: property(lambda self: self._target)):
            effects = handler.handle()

        assert len(effects) == 1
        url = mock_modal.call_args.kwargs["url"]
        assert "note_id=" in url and "note-uuid" not in url


# --- CustomerHTMLApi Authentication ---


class TestAuthentication:
    def _make_handler(self, request, secrets):
        handler = CustomerHTMLApi.__new__(CustomerHTMLApi)
        handler.request = request
        handler.secrets = secrets
        return handler

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_staff_session_authenticates(self, mock_session_cls, mock_request, mock_secrets):
        mock_session_cls.return_value.logged_in_user = {"id": "staff-1", "type": "Staff"}
        handler = self._make_handler(mock_request, mock_secrets)

        result = handler.authenticate(MagicMock())

        assert result is True
        assert mock_session_cls.mock_calls == [call(mock_request)]

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_non_staff_session_falls_to_api_key(self, mock_session_cls, mock_request, mock_secrets):
        mock_session_cls.return_value.logged_in_user = {"id": "patient-1", "type": "Patient"}
        mock_request.headers = {"Authorization": "test-secret-key-123"}
        handler = self._make_handler(mock_request, mock_secrets)

        result = handler.authenticate(MagicMock())

        assert result is True

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_invalid_session_falls_to_api_key(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "test-secret-key-123"}
        handler = self._make_handler(mock_request, mock_secrets)

        result = handler.authenticate(MagicMock())

        assert result is True

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_invalid_api_key_rejected(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "wrong-key"}
        handler = self._make_handler(mock_request, mock_secrets)

        result = handler.authenticate(MagicMock())

        assert result is False

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_missing_secret_rejected(self, mock_session_cls, mock_request):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "any-key"}
        handler = self._make_handler(mock_request, {})

        result = handler.authenticate(MagicMock())

        assert result is False

    @patch("patient_visit_summary.handlers.patient_visit_summary.SessionCredentials")
    def test_missing_auth_header_rejected(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {}
        handler = self._make_handler(mock_request, mock_secrets)

        result = handler.authenticate(MagicMock())

        assert result is False


# --- NoteDataExtractor: Fetch Command Helpers ---


def _make_extractor(mock_patient, mock_note):
    """Build a NoteDataExtractor bypassing __init__."""
    extractor = NoteDataExtractor.__new__(NoteDataExtractor)
    extractor.patient = mock_patient
    extractor.note = mock_note
    return extractor


class TestFetchCommandHelpers:
    def test_fetch_latest_command_data_in_note_by_type(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch(f"{_NDE}.Command") as mock_command_cls:
            mock_qs = mock_command_cls.objects.filter.return_value.order_by.return_value.values_list.return_value
            mock_qs.first.return_value = {"narrative": "test"}

            result = extractor._fetch_latest_command_data("hpi")

        assert result == {"narrative": "test"}
        assert mock_command_cls.objects.filter.mock_calls == [
            call(schema_key="hpi", note=mock_note, entered_in_error__isnull=True, state="committed"),
            call().order_by("-dbid"),
            call().order_by().values_list("data", flat=True),
            call().order_by().values_list().first(),
        ]

    def test_fetch_all_commands_data_in_note_by_type(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch(f"{_NDE}.Command") as mock_command_cls:
            mock_qs = mock_command_cls.objects.filter.return_value.order_by.return_value.values_list.return_value
            mock_qs.all.return_value = [{"narrative": "a"}, {"narrative": "b"}]

            result = extractor._fetch_all_commands_data("plan")

        assert result == [{"narrative": "a"}, {"narrative": "b"}]
        assert mock_command_cls.objects.filter.mock_calls == [
            call(schema_key="plan", note=mock_note, entered_in_error__isnull=True, state="committed"),
            call().order_by("dbid"),
            call().order_by().values_list("data", flat=True),
            call().order_by().values_list().all(),
        ]

    def test_fetch_commands_fields_in_note_by_type(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch(f"{_NDE}.Command") as mock_command_cls:
            mock_qs = mock_command_cls.objects.filter.return_value.order_by.return_value.values.return_value
            mock_qs.all.return_value = [{"data": {}, "modified": "2025-01-01"}]

            result = extractor._fetch_commands_fields("diagnose", "data", "modified")

        assert result == [{"data": {}, "modified": "2025-01-01"}]
        assert mock_command_cls.objects.filter.mock_calls == [
            call(schema_key="diagnose", note=mock_note, entered_in_error__isnull=True, state="committed"),
            call().order_by("dbid"),
            call().order_by().values("data", "modified"),
            call().order_by().values().all(),
        ]


# --- format_ros_or_physical_exam_from_note ---


class TestFormatRosOrPhysicalExamFromNote:
    def _make_extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_mult_question_answers(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {"text": "Constitutional"},
                "question_1": [
                    {"text": "Fever", "selected": True},
                    {"text": "Chills", "selected": False},
                    {"text": "Fatigue", "selected": True},
                ],
            }
        ]
        ros_data[0]["questionnaire"]["extra"] = {
            "questions": [
                {"pk": 1, "label": "Symptoms", "name": "question_1", "type": "MULT"}
            ]
        }

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert len(result) == 1
        assert result[0]["questionnaire"] == "Constitutional"
        assert result[0]["questions_and_answers"][0]["label"] == "Symptoms"
        assert result[0]["questions_and_answers"][0]["answer"] == "Fever, Fatigue"

    def test_txt_question_answers(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Notes",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Comment", "name": "comment_field", "type": "TXT"}
                        ]
                    },
                },
                "comment_field": "Patient reports mild pain",
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert result[0]["questions_and_answers"][0]["answer"] == "Patient reports mild pain"

    def test_skipped_question_excluded(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Review",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Skipped Q", "name": "q1", "type": "MULT"},
                            {"pk": 2, "label": "Answered Q", "name": "q2", "type": "TXT"},
                        ]
                    },
                },
                "skip-1": False,
                "q1": [{"text": "A", "selected": True}],
                "q2": "Some text",
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert len(result[0]["questions_and_answers"]) == 1
        assert result[0]["questions_and_answers"][0]["label"] == "Answered Q"

    def test_empty_answers_excluded(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Review",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Nothing selected", "name": "q1", "type": "MULT"},
                        ]
                    },
                },
                "q1": [{"text": "A", "selected": False}, {"text": "B", "selected": False}],
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert result[0]["questions_and_answers"] == []


# --- format_questionnaires_from_note ---


class TestFormatQuestionnairesFromNote:
    def _make_questionnaire_data(self, questions, answers, name="Test Questionnaire"):
        data = {
            "modified": "2025-01-15T10:00:00Z",
            "data": {
                "questionnaire": {
                    "text": name,
                    "extra": {"questions": questions},
                },
            },
        }
        for key, value in answers.items():
            data["data"][key] = value
        return data

    def test_mult_question(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {
                "label": "Symptoms",
                "name": "q1",
                "type": "MULT",
                "coding": {"code": "SYM-1"},
            }
        ]
        answers = {"q1": [{"text": "Cough", "selected": True}, {"text": "Fever", "selected": False}]}
        raw_data = [self._make_questionnaire_data(questions, answers)]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires()

        assert len(result) == 1
        assert result[0]["name"] == "Test Questionnaire"
        assert result[0]["questions_and_answers"][0]["answer"] == "Cough"

    def test_txt_question(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {"label": "Notes", "name": "q1", "type": "TXT", "coding": {"code": "NOTE-1"}}
        ]
        answers = {"q1": "Free text answer"}
        raw_data = [self._make_questionnaire_data(questions, answers)]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires()

        assert result[0]["questions_and_answers"][0]["answer"] == "Free text answer"

    def test_int_question(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {"label": "Score", "name": "q1", "type": "INT", "coding": {"code": "SCR-1"}}
        ]
        answers = {"q1": 42}
        raw_data = [self._make_questionnaire_data(questions, answers)]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires()

        assert result[0]["questions_and_answers"][0]["answer"] == "42"

    def test_sing_question(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {
                "label": "Severity",
                "name": "q1",
                "type": "SING",
                "coding": {"code": "SEV-1"},
                "options": [
                    {"pk": 10, "label": "Mild"},
                    {"pk": 20, "label": "Severe"},
                ],
            }
        ]
        answers = {"q1": 20}
        raw_data = [self._make_questionnaire_data(questions, answers)]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires()

        assert result[0]["questions_and_answers"][0]["answer"] == "Severe"

    def test_uses_structured_assessment_schema_key(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch.object(extractor, "_fetch_commands_fields", return_value=[]) as mock_fetch:
            extractor._format_questionnaires(questionnaire_type="structuredAssessment")

        mock_fetch.assert_called_once_with("structuredAssessment", "data", "modified")

    def test_defaults_to_questionnaire_schema_key(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch.object(extractor, "_fetch_commands_fields", return_value=[]) as mock_fetch:
            extractor._format_questionnaires()

        mock_fetch.assert_called_once_with("questionnaire", "data", "modified")

    def test_questionnaire_result_included_when_present(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {"label": "Q", "name": "q1", "type": "TXT", "coding": {"code": "Q-1"}}
        ]
        data = self._make_questionnaire_data(questions, {"q1": "answer"})
        data["data"]["result"] = "Score: 10"

        with patch.object(extractor, "_fetch_commands_fields", return_value=[data]):
            result = extractor._format_questionnaires()

        assert result[0]["result"] == "Score: 10"


# --- get_diagnoses_from_structured_assessments ---


class TestGetDiagnosesFromStructuredAssessments:
    def test_no_structured_assessments_returns_empty(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        with patch.object(extractor, "_fetch_all_commands_data", return_value=[]):
            result = extractor._get_diagnoses_from_structured_assessments()

        assert result == []

    def test_no_icd10_codes_returns_empty(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        assessment_data = [
            {
                "questionnaire": {"extra": {"pk": 1, "questions": []}},
            }
        ]

        with (
            patch.object(extractor, "_fetch_all_commands_data", return_value=assessment_data),
            patch(f"{_NDE}.InterviewQuestionResponse") as mock_iqr,
        ):
            mock_iqr.objects.filter.return_value.values_list.return_value = []
            result = extractor._get_diagnoses_from_structured_assessments()

        assert result == []

    @patch(f"{_NDE}.Assessment")
    @patch(f"{_NDE}.InterviewQuestionResponse")
    def test_extracts_diagnoses_from_sing_questions(self, mock_iqr, mock_assessment_cls, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        assessment_data = [
            {
                "questionnaire": {
                    "extra": {
                        "pk": 1,
                        "questions": [
                            {
                                "pk": 100,
                                "name": "q1",
                                "type": "SING",
                                "options": [
                                    {"pk": 10, "code": "E119"},
                                    {"pk": 20, "code": "E785"},
                                ],
                            }
                        ],
                    }
                },
                "q1": 10,
            }
        ]

        mock_iqr.objects.filter.return_value.values_list.return_value = [(1, 100)]

        mock_coding = MagicMock()
        mock_coding.display = "Type 2 Diabetes"
        mock_coding.code = "E119"
        mock_coding.system = "ICD-10"
        mock_condition = MagicMock()
        mock_condition.codings.all.return_value = [mock_coding]
        mock_assessment_obj = MagicMock()
        mock_assessment_obj.condition = mock_condition
        mock_assessment_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value = [
            mock_assessment_obj
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=assessment_data):
            result = extractor._get_diagnoses_from_structured_assessments()

        assert result == [("Type 2 Diabetes", "E11.9")]

    @patch(f"{_NDE}.Assessment")
    @patch(f"{_NDE}.InterviewQuestionResponse")
    def test_extracts_diagnoses_from_mult_questions(self, mock_iqr, mock_assessment_cls, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        assessment_data = [
            {
                "questionnaire": {
                    "extra": {
                        "pk": 1,
                        "questions": [
                            {
                                "pk": 100,
                                "name": "q1",
                                "type": "MULT",
                                "options": [
                                    {"pk": 10, "code": "E119"},
                                    {"pk": 20, "code": "E785"},
                                ],
                            }
                        ],
                    }
                },
                "q1": [
                    {"value": 10, "selected": True},
                    {"value": 20, "selected": False},
                ],
            }
        ]

        mock_iqr.objects.filter.return_value.values_list.return_value = [(1, 100)]

        mock_coding = MagicMock()
        mock_coding.display = "Type 2 Diabetes"
        mock_coding.code = "E119"
        mock_coding.system = "ICD-10"
        mock_condition = MagicMock()
        mock_condition.codings.all.return_value = [mock_coding]
        mock_assessment_obj = MagicMock()
        mock_assessment_obj.condition = mock_condition
        mock_assessment_cls.objects.filter.return_value.select_related.return_value.prefetch_related.return_value = [
            mock_assessment_obj
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=assessment_data):
            result = extractor._get_diagnoses_from_structured_assessments()

        assert result == [("Type 2 Diabetes", "E11.9")]


# --- Index endpoint ---


class TestIndex:
    def _make_handler(self, request):
        handler = CustomerHTMLApi.__new__(CustomerHTMLApi)
        handler.request = request
        handler.secrets = {"display_timezone": "US/Eastern"}
        return handler

    @patch("patient_visit_summary.handlers.patient_visit_summary.render_to_string")
    @patch("patient_visit_summary.handlers.patient_visit_summary.NoteDataExtractor")
    def test_returns_html_response(self, mock_extractor_cls, mock_render, mock_request, mock_patient, mock_note, mock_provider):
        mock_request.query_params = {"patient_id": "p1", "note_id": "n1"}
        mock_extractor = MagicMock()
        mock_extractor.get_template_context.return_value = {
            "patient": mock_patient,
            "note": mock_note,
            "provider": mock_provider,
            "reason_for_visit": "Annual checkup",
        }
        mock_extractor_cls.return_value = mock_extractor
        mock_render.return_value = "<html>test</html>"

        handler = self._make_handler(mock_request)
        result = handler.index()

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK

    @patch("patient_visit_summary.handlers.patient_visit_summary.render_to_string")
    @patch("patient_visit_summary.handlers.patient_visit_summary.NoteDataExtractor")
    def test_falls_back_to_note_provider_when_no_appointment(self, mock_extractor_cls, mock_render, mock_request, mock_patient, mock_note, mock_provider):
        mock_request.query_params = {"patient_id": "p1", "note_id": "n1"}
        mock_extractor = MagicMock()
        mock_extractor.get_template_context.return_value = {
            "patient": mock_patient,
            "note": mock_note,
            "provider": mock_provider,
        }
        mock_extractor_cls.return_value = mock_extractor
        mock_render.return_value = "<html>test</html>"

        handler = self._make_handler(mock_request)
        result = handler.index()

        assert len(result) == 1

    @patch("patient_visit_summary.handlers.patient_visit_summary.render_to_string")
    @patch("patient_visit_summary.handlers.patient_visit_summary.NoteDataExtractor")
    def test_unstructured_rfv_uses_comment(self, mock_extractor_cls, mock_render, mock_request, mock_patient, mock_note, mock_provider):
        mock_request.query_params = {"patient_id": "p1", "note_id": "n1"}
        mock_extractor = MagicMock()
        mock_extractor.get_template_context.return_value = {
            "patient": mock_patient,
            "note": mock_note,
            "provider": mock_provider,
            "reason_for_visit": "Knee pain",
        }
        mock_extractor_cls.return_value = mock_extractor
        mock_render.return_value = "<html>test</html>"

        handler = self._make_handler(mock_request)
        result = handler.index()

        assert len(result) == 1


# --- Vitals enum mapping ---


class TestVitalsEnumMapping:
    def test_vitals_enums_are_translated(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        vitals_data = [
            {
                "blood_pressure_position_and_site": "0",
                "body_temperature_site": "1",
                "pulse_rhythm": "0",
                "height": "70",
                "weight_lbs": "180",
                "weight_oz": "8",
            }
        ]

        with (
            patch.object(extractor, "_fetch_all_commands_data", return_value=vitals_data),
            patch.object(extractor, "_fetch_latest_command_data", return_value=None),
            patch.object(extractor, "_fetch_commands_fields", return_value=[]),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ):
            context = extractor.get_template_context()

        vitals = context["vitals_commands_data"][0]
        assert vitals["blood_pressure_position_and_site"] == "Sitting, Right Upper Extremity"
        assert vitals["body_temperature_site"] == "Oral"
        assert vitals["pulse_rhythm"] == "Regular"
        # weight_oz (singular, the SDK key) passes through untouched, and BMI is
        # computed for the PVS printout (was previously never set -> always blank).
        assert vitals["weight_oz"] == "8"
        assert vitals["bmi"] == "25.9"


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.first_name = "Jane"
    provider.last_name = "Doe"
    return provider


# --- Index: follow-up, assessments, diagnoses, goals, medical history ---


class TestIndexFollowUp:
    """Tests for follow-up command handling inside get_template_context()."""

    def _setup_extractor(self, mock_patient, mock_note, mock_provider, fetch_all_side_effect=None, fetch_latest_return=None):
        extractor = _make_extractor(mock_patient, mock_note)
        patches = [
            patch.object(extractor, "_fetch_all_commands_data", side_effect=fetch_all_side_effect or (lambda sk: [])),
            patch.object(extractor, "_fetch_latest_command_data", return_value=fetch_latest_return),
            patch.object(extractor, "_fetch_commands_fields", return_value=[]),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ]
        return extractor, patches

    def test_follow_up_with_structured_rfv(self, mock_patient, mock_note, mock_provider):
        follow_up_data = {
            "requested_date": {"date": "2025-06-15"},
            "coding": {"text": "Follow-up visit"},
            "note_type": {"text": "Office Visit"},
        }

        extractor, patches = self._setup_extractor(
            mock_patient, mock_note, mock_provider,
            fetch_all_side_effect=lambda sk: [follow_up_data] if sk == "followUp" else [],
        )
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["follow_up_date"] == "2025-06-15"
            assert context["follow_up_rfv"] == "Follow-up visit"
            assert context["follow_up_note_type"] == "Office Visit"
        finally:
            for p in patches:
                p.stop()

    def test_follow_up_with_unstructured_rfv(self, mock_patient, mock_note, mock_provider):
        follow_up_data = {
            "requested_date": {"date": "2025-06-15"},
            "reason_for_visit": "Knee pain check",
            "note_type": {"text": "Telehealth"},
        }

        extractor, patches = self._setup_extractor(
            mock_patient, mock_note, mock_provider,
            fetch_all_side_effect=lambda sk: [follow_up_data] if sk == "followUp" else [],
        )
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["follow_up_rfv"] == "Knee pain check"
        finally:
            for p in patches:
                p.stop()

    def test_assessment_status_mapped(self, mock_patient, mock_note, mock_provider):
        def fetch_all(schema_key):
            if schema_key == "assess":
                return [{"status": "improved", "condition": {"text": "HTN"}}]
            return []

        extractor, patches = self._setup_extractor(
            mock_patient, mock_note, mock_provider,
            fetch_all_side_effect=fetch_all,
        )
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["assessments_commands_data"][0]["status"] == "Improved"
        finally:
            for p in patches:
                p.stop()

    def test_diagnose_commands_date_formatted(self, mock_patient, mock_note, mock_provider):
        extractor = _make_extractor(mock_patient, mock_note)
        diag_data = [{"data": {"diagnose": {"text": "HTN"}}, "modified": "2025-01-15T14:30:00Z"}]

        patches = [
            patch.object(extractor, "_fetch_all_commands_data", return_value=[]),
            patch.object(extractor, "_fetch_latest_command_data", return_value=None),
            patch.object(extractor, "_fetch_commands_fields", return_value=diag_data),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ]
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert len(context["diagnose_commands_data"]) == 1
            assert "at" in context["diagnose_commands_data"][0]["modified"]
            assert "EDT" in context["diagnose_commands_data"][0]["modified"]
        finally:
            for p in patches:
                p.stop()

    @patch(f"{_NDE}.GoalAchievementStatus")
    @patch(f"{_NDE}.GoalPriority")
    def test_goal_enums_mapped(self, mock_priority_cls, mock_achievement_cls, mock_patient, mock_note, mock_provider):
        mock_priority_cls.return_value.label = "High"
        mock_achievement_cls.return_value.label = "In Progress"

        def fetch_all(schema_key):
            if schema_key == "goal":
                return [{"priority": "high-priority", "achievement_status": "in-progress", "goal_statement": "Lose weight"}]
            return []

        extractor = _make_extractor(mock_patient, mock_note)
        patches = [
            patch.object(extractor, "_fetch_all_commands_data", side_effect=fetch_all),
            patch.object(extractor, "_fetch_latest_command_data", return_value=None),
            patch.object(extractor, "_fetch_commands_fields", return_value=[]),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ]
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["goal_commands_data"][0]["priority"] == "High"
            assert context["goal_commands_data"][0]["achievement_status"] == "In Progress"
        finally:
            for p in patches:
                p.stop()

    @patch(f"{_NDE}.GoalAchievementStatus")
    @patch(f"{_NDE}.GoalPriority")
    def test_update_goal_enums_mapped(self, mock_priority_cls, mock_achievement_cls, mock_patient, mock_note, mock_provider):
        mock_priority_cls.return_value.label = "Medium"
        mock_achievement_cls.return_value.label = "Achieved"

        def fetch_all(schema_key):
            if schema_key == "updateGoal":
                return [{"priority": "medium-priority", "achievement_status": "achieved", "goal_statement": {"text": "Exercise"}}]
            return []

        extractor = _make_extractor(mock_patient, mock_note)
        patches = [
            patch.object(extractor, "_fetch_all_commands_data", side_effect=fetch_all),
            patch.object(extractor, "_fetch_latest_command_data", return_value=None),
            patch.object(extractor, "_fetch_commands_fields", return_value=[]),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ]
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["update_goal_commands_data"][0]["priority"] == "Medium"
            assert context["update_goal_commands_data"][0]["achievement_status"] == "Achieved"
        finally:
            for p in patches:
                p.stop()

    def test_medical_history_icd10_formatted(self, mock_patient, mock_note, mock_provider):
        def fetch_all(schema_key):
            if schema_key == "medicalHistory":
                return [{"past_medical_history": {"text": "Diabetes", "annotations": ["E119"]}}]
            return []

        extractor = _make_extractor(mock_patient, mock_note)
        patches = [
            patch.object(extractor, "_fetch_all_commands_data", side_effect=fetch_all),
            patch.object(extractor, "_fetch_latest_command_data", return_value=None),
            patch.object(extractor, "_fetch_commands_fields", return_value=[]),
            patch.object(extractor, "_format_questionnaires", return_value=[]),
            patch.object(extractor, "_format_ros_or_exam", return_value=[]),
            patch.object(extractor, "_get_diagnoses_from_structured_assessments", return_value=[]),
            patch.object(extractor, "_get_header_context", return_value={
                "provider": mock_provider,
                "provider_top_role": None,
                "appointment_date": "January 15, 2025",
            }),
            patch.object(extractor, "_get_reason_for_visit", return_value=""),
        ]
        for p in patches:
            p.start()
        try:
            context = extractor.get_template_context()
            assert context["medical_history_commands_data"][0]["past_medical_history"]["annotations"][0] == "E11.9"
        finally:
            for p in patches:
                p.stop()


# --- Questionnaire name filtering ---


class TestQuestionnaireNameFiltering:
    def test_filters_by_questionnaire_names(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        raw_data = [
            {
                "modified": "2025-01-15T10:00:00Z",
                "data": {
                    "questionnaire": {
                        "text": "PHQ-9",
                        "extra": {"questions": [{"label": "Q", "name": "q1", "type": "TXT", "coding": {"code": "Q-1"}}]},
                    },
                    "q1": "answer",
                },
            },
            {
                "modified": "2025-01-15T10:00:00Z",
                "data": {
                    "questionnaire": {
                        "text": "Other",
                        "extra": {"questions": [{"label": "Q", "name": "q1", "type": "TXT", "coding": {"code": "Q-1"}}]},
                    },
                    "q1": "other answer",
                },
            },
        ]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires(questionnaire_names=["PHQ-9"])

        assert len(result) == 1
        assert result[0]["name"] == "PHQ-9"


# --- get_css ---


class TestGetCss:
    @patch("patient_visit_summary.handlers.patient_visit_summary.render_to_string")
    def test_returns_css_response(self, mock_render):
        mock_render.return_value = "body { color: red; }"
        handler = CustomerHTMLApi.__new__(CustomerHTMLApi)

        result = handler.get_css()

        assert len(result) == 1
        response = result[0]
        assert response.status_code == HTTPStatus.OK
        assert response.headers == {"Content-Type": "text/css"}
        assert mock_render.mock_calls == [call("templates/style.css")]


# --- ROS/Physical Exam/Questionnaire comments ---


class TestCommentsInAnswers:
    """Tests for comment display in MULT-type answers."""

    def test_ros_mult_with_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Constitutional",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Symptoms", "name": "q1", "type": "MULT"}
                        ]
                    },
                },
                "q1": [
                    {"text": "Fever", "selected": True, "comment": "low grade"},
                    {"text": "Chills", "selected": True},
                    {"text": "Fatigue", "selected": False},
                ],
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        # Comments are not currently rendered in _format_ros_or_exam; just selected items
        assert "Fever" in result[0]["questions_and_answers"][0]["answer"]
        assert "Chills" in result[0]["questions_and_answers"][0]["answer"]

    def test_ros_mult_without_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Constitutional",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Symptoms", "name": "q1", "type": "MULT"}
                        ]
                    },
                },
                "q1": [
                    {"text": "Fever", "selected": True},
                    {"text": "Chills", "selected": True},
                ],
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert result[0]["questions_and_answers"][0]["answer"] == "Fever, Chills"

    def test_ros_mult_with_empty_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        ros_data = [
            {
                "questionnaire": {
                    "text": "Constitutional",
                    "extra": {
                        "questions": [
                            {"pk": 1, "label": "Symptoms", "name": "q1", "type": "MULT"}
                        ]
                    },
                },
                "q1": [
                    {"text": "Fever", "selected": True, "comment": ""},
                ],
            }
        ]

        with patch.object(extractor, "_fetch_all_commands_data", return_value=ros_data):
            result = extractor._format_ros_or_exam("ros")

        assert "Fever" in result[0]["questions_and_answers"][0]["answer"]

    def test_questionnaire_mult_with_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        questions = [
            {
                "label": "Symptoms",
                "name": "q1",
                "type": "MULT",
                "coding": {"code": "SYM-1"},
            }
        ]
        data = {
            "modified": "2025-01-15T10:00:00Z",
            "data": {
                "questionnaire": {
                    "text": "Test Questionnaire",
                    "extra": {"questions": questions},
                },
                "q1": [
                    {"text": "Cough", "selected": True, "comment": "dry"},
                    {"text": "Fever", "selected": True},
                ],
            },
        }

        with patch.object(extractor, "_fetch_commands_fields", return_value=[data]):
            result = extractor._format_questionnaires()

        # Comments are not currently rendered; just selected items
        assert "Cough" in result[0]["questions_and_answers"][0]["answer"]
        assert "Fever" in result[0]["questions_and_answers"][0]["answer"]


# --- Close Goal (no longer in NoteDataExtractor; omitted as out-of-scope) ---
# --- Reason for Visit comment (handled in _get_reason_for_visit) ---


class TestReasonForVisitComment:
    """Tests for RFV comment field being passed to template context."""

    def test_structured_rfv_with_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        rfv_command = MagicMock()
        rfv_command.data = {"coding": {"text": "Annual checkup"}, "comment": "Patient also wants to discuss knee pain"}

        with patch(f"{_NDE}.Command") as mock_cmd_cls:
            mock_cmd_cls.objects.filter.return_value.order_by.return_value.__iter__ = MagicMock(
                return_value=iter([rfv_command])
            )
            result = extractor._get_reason_for_visit()

        assert result == "Annual checkup (Patient also wants to discuss knee pain)"

    def test_structured_rfv_without_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        rfv_command = MagicMock()
        rfv_command.data = {"coding": {"text": "Annual checkup"}}

        with patch(f"{_NDE}.Command") as mock_cmd_cls:
            mock_cmd_cls.objects.filter.return_value.order_by.return_value.__iter__ = MagicMock(
                return_value=iter([rfv_command])
            )
            result = extractor._get_reason_for_visit()

        assert result == "Annual checkup"

    def test_unstructured_rfv_has_no_comment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        rfv_command = MagicMock()
        rfv_command.data = {"comment": "Knee pain"}

        with patch(f"{_NDE}.Command") as mock_cmd_cls:
            mock_cmd_cls.objects.filter.return_value.order_by.return_value.__iter__ = MagicMock(
                return_value=iter([rfv_command])
            )
            result = extractor._get_reason_for_visit()

        assert result == "Knee pain"
