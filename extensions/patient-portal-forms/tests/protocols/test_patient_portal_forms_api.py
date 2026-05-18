"""Tests for ProviderQuestionnaireAPI and PatientQuestionnaireAPI.

The SimpleAPI base class indexes registered routes at __init__ time, so
these tests construct API instances via __new__ and stub the `request`
attribute, mirroring the pattern used in the patient_communications plugin.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.commands.commands.questionnaire.question import ResponseOption
from canvas_sdk.effects import EffectType
from http import HTTPStatus

from patient_portal_forms.protocols.patient_portal_forms_api import (
    PatientQuestionnaireAPI,
    ProviderQuestionnaireAPI,
)


def _build_provider_api(
    *,
    patient_id: str = "patient-1",
    staff_id: str = "staff-1",
    body: dict | None = None,
) -> ProviderQuestionnaireAPI:
    api = ProviderQuestionnaireAPI.__new__(ProviderQuestionnaireAPI)
    api.request = MagicMock()
    api.request.path_params = {"patient_id": patient_id}
    api.request.json.return_value = body or {}
    api.event = MagicMock()
    api.event.context = {"headers": {"canvas-logged-in-user-id": staff_id}}
    return api


def _build_patient_api(
    *,
    patient_id: str = "patient-1",
    questionnaire_name: str | None = None,
    body: dict | None = None,
) -> PatientQuestionnaireAPI:
    api = PatientQuestionnaireAPI.__new__(PatientQuestionnaireAPI)
    api.request = MagicMock()
    api.request.path_params = (
        {"patient_id": patient_id, "questionnaire_name": questionnaire_name}
        if questionnaire_name
        else {"patient_id": patient_id}
    )
    api.request.json.return_value = body or {}
    api.event = MagicMock()
    return api


# ----- Provider API ---------------------------------------------------------


class TestProviderQuestionnaireAPI:
    def test_get_patient_forms_404_when_patient_missing(self):
        api = _build_provider_api()
        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Patient.objects"
        ) as mock_patient_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>404</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.HTMLResponse"
        ) as mock_html:
            mock_patient_objects.filter.return_value.exists.return_value = False
            mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
            api.get_patient_forms()
        assert mock_html.call_args.kwargs["status_code"] == HTTPStatus.NOT_FOUND

    def test_get_patient_forms_passes_grouped_assignments_to_template(self):
        api = _build_provider_api()
        grouped = {
            "pending_items": [{"questionnaire_name": "PHQ-9"}],
            "completed_groups": [{"questionnaire_name": "GAD-7", "submission_count": 2}],
            "pending_names": ["PHQ-9"],
        }

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Patient.objects"
        ) as mock_patient_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Staff.objects"
        ) as mock_staff_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string"
        ) as mock_render, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.HTMLResponse"
        ) as mock_html:
            mock_patient_objects.filter.return_value.exists.return_value = True
            mock_staff_objects.get.return_value = MagicMock()
            mock_q_objects.filter.return_value.order_by.return_value = []
            mock_service.list_grouped.return_value = grouped
            mock_render.return_value = "<html>ok</html>"
            mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            api.get_patient_forms()

        # The template gets pending_items + completed_groups + pending_names
        mock_service.list_grouped.assert_called_once_with("patient-1")
        ctx = mock_render.call_args.kwargs["context"]
        assert ctx["pending_items"] == grouped["pending_items"]
        assert ctx["completed_groups"] == grouped["completed_groups"]
        assert ctx["pending_names"] == grouped["pending_names"]

    def test_assign_forms_delegates_to_service_and_sends_message(self):
        staff_id = str(uuid.uuid4())
        payload = {
            "questionnaires": [
                {
                    "questionnaire_name": "PHQ-9",
                    "due_date": "2026-06-01",
                    "assigning_provider": {"key": staff_id, "name": "Dr. Smith"},
                }
            ]
        }
        api = _build_provider_api(staff_id=staff_id, body=payload)

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>msg</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Message"
        ) as mock_message_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Response"
        ) as mock_response_cls:
            sent_effect = MagicMock(type=EffectType.CREATE_MESSAGE)
            mock_message_cls.return_value.create_and_send.return_value = sent_effect
            response_effect = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
            mock_response_cls.return_value = response_effect

            result = api.assign_forms()

        # Service is called with the patient id and questionnaires list;
        # the assigning provider comes from the trusted session header,
        # passed in as a kwarg.
        mock_service.assign.assert_called_once_with(
            "patient-1",
            payload["questionnaires"],
            assigning_provider_uuid=staff_id,
        )
        assert result == [sent_effect, response_effect]
        assert mock_response_cls.call_args.kwargs["status_code"] == HTTPStatus.CREATED

    def test_assign_forms_with_empty_list_calls_service_with_empty_list(self):
        """Defensive: an empty payload should not blow up."""
        api = _build_provider_api(staff_id="header-staff", body={"questionnaires": []})

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>msg</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Message"
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Response"
        ):
            api.assign_forms()

        mock_service.assign.assert_called_once_with(
            "patient-1", [], assigning_provider_uuid="header-staff"
        )

    def test_assign_forms_ignores_body_assigning_provider_uses_session_header(self):
        """Security regression: the assigning staff must come from the
        trusted session header (``canvas-logged-in-user-id``), not from
        the request body. Without this, an authenticated staff member
        could craft a POST substituting another staff's UUID and the
        resulting Patient Portal Form note (on submit) would land under
        the impersonated staff's name, location, and worklist."""
        legit_staff_id = str(uuid.uuid4())
        attacker_target_id = str(uuid.uuid4())
        assert legit_staff_id != attacker_target_id

        payload = {
            "questionnaires": [
                {
                    "questionnaire_name": "PHQ-9",
                    "due_date": "2026-06-01",
                    # Body claims a different staff than the session header.
                    "assigning_provider": {
                        "key": attacker_target_id,
                        "name": "Impersonated Provider",
                    },
                }
            ]
        }
        api = _build_provider_api(staff_id=legit_staff_id, body=payload)

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>msg</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Message"
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Response"
        ):
            api.assign_forms()

        # The service was called with the session header's staff id,
        # not the body-supplied id.
        call = mock_service.assign.call_args
        assert call.kwargs["assigning_provider_uuid"] == legit_staff_id
        assert call.kwargs["assigning_provider_uuid"] != attacker_target_id

    def test_send_reminder_does_not_touch_db(self):
        api = _build_provider_api(
            body={"questionnaire_name": "PHQ-9", "due_date": "2026-06-01"}
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>r</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Message"
        ) as mock_message_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Response"
        ) as mock_response_cls:
            mock_message_cls.return_value.create_and_send.return_value = MagicMock(
                type=EffectType.CREATE_MESSAGE
            )
            mock_response_cls.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            api.send_reminder()

        mock_service.assign.assert_not_called()
        mock_service.unassign.assert_not_called()
        mock_message_cls.assert_called_once()

    def test_unassign_form_calls_service(self):
        api = _build_provider_api(body={"questionnaire_name": "PHQ-9"})

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Response"
        ) as mock_response_cls:
            mock_response_cls.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
            result = api.unassign_form()

        mock_service.unassign.assert_called_once_with("patient-1", "PHQ-9")
        assert len(result) == 1
        assert mock_response_cls.call_args.kwargs["status_code"] == HTTPStatus.CREATED


# ----- Patient API auth -----------------------------------------------------


class TestPatientQuestionnaireAPIAuth:
    def test_matching_patient_is_allowed(self):
        pid = str(uuid.uuid4())
        api = _build_patient_api(patient_id=pid)
        creds = MagicMock(logged_in_user={"type": "Patient", "id": pid})
        assert api.authenticate(creds) is True

    def test_other_patient_is_denied(self):
        api = _build_patient_api(patient_id=str(uuid.uuid4()))
        creds = MagicMock(logged_in_user={"type": "Patient", "id": str(uuid.uuid4())})
        assert api.authenticate(creds) is False

    def test_staff_user_type_is_denied(self):
        pid = str(uuid.uuid4())
        api = _build_patient_api(patient_id=pid)
        creds = MagicMock(logged_in_user={"type": "Staff", "id": pid})
        assert api.authenticate(creds) is False


# ----- Patient API reads ----------------------------------------------------


class TestPatientQuestionnaireAPIRead:
    def test_get_questionnaire_questions_routes_to_fill_out_when_outstanding_exists(self):
        staff_id = str(uuid.uuid4())
        api = _build_patient_api(questionnaire_name="PHQ-9")

        mock_questionnaire = MagicMock()
        mock_questionnaire.id = uuid.uuid4()
        mock_questionnaire.name = "PHQ-9"
        mock_questionnaire.questions.order_by.return_value.select_related.return_value.prefetch_related.return_value = []

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string"
        ) as mock_render, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.HTMLResponse"
        ) as mock_html:
            mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
            mock_service.get_one.return_value = {
                "questionnaire_name": "PHQ-9",
                "due_date": "2026-06-01",
                "assigning_provider": {"key": staff_id, "name": "Dr. Smith"},
            }
            mock_render.return_value = "<html>q</html>"
            mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            api.get_questionnaire_questions()

        # The fill-out template was rendered (not the review template).
        template = mock_render.call_args.args[0]
        assert "fill_out" in template
        ctx = mock_render.call_args.kwargs["context"]
        assert ctx["due_date"] == "2026-06-01"
        assert ctx["assigning_provider_id"] == staff_id

    def test_get_questionnaire_questions_routes_to_review_when_only_history(self):
        """Reassignment-vs-review precedence: an outstanding row routes to
        fill-out; only-completed-history routes to review."""
        api = _build_patient_api(questionnaire_name="PHQ-9")

        mock_questionnaire = MagicMock()
        mock_questionnaire.id = uuid.uuid4()
        mock_questionnaire.name = "PHQ-9"
        mock_questionnaire.questions.order_by.return_value.select_related.return_value.prefetch_related.return_value = []

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string"
        ) as mock_render, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.HTMLResponse"
        ) as mock_html:
            mock_q_objects.filter.return_value.first.return_value = mock_questionnaire
            mock_service.get_one.return_value = None
            mock_service.get_completed_entries.return_value = [
                {
                    "questionnaire_name": "PHQ-9",
                    "completed_date": "2026-05-01",
                    "submitted_answers": [],
                    "assigning_provider": {"key": "s", "name": "n"},
                }
            ]
            mock_render.return_value = "<html>review</html>"
            mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            api.get_questionnaire_questions()

        template = mock_render.call_args.args[0]
        assert "review" in template

    def test_get_questionnaire_questions_returns_404_when_questionnaire_missing(self):
        api = _build_patient_api(questionnaire_name="Ghost")

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.render_to_string",
            return_value="<html>404</html>",
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.HTMLResponse"
        ) as mock_html:
            mock_q_objects.filter.return_value.first.return_value = None
            mock_service.get_one.return_value = None
            mock_service.get_completed_entries.return_value = []
            mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
            api.get_questionnaire_questions()

        assert mock_html.call_args.kwargs["status_code"] == HTTPStatus.NOT_FOUND


# ----- Patient API submit ---------------------------------------------------


class TestPatientQuestionnaireSubmit:
    def _api(self, patient_id: str, staff_id: str, qa_list: list[dict]) -> PatientQuestionnaireAPI:
        return _build_patient_api(
            patient_id=patient_id,
            body={
                "questionnaire_id": str(uuid.uuid4()),
                "questionnaire_name": "PHQ-9",
                "assigning_staff_id": staff_id,
                "questions_and_answers": qa_list,
            },
        )

    def test_submit_returns_422_when_no_outstanding_assignment(self):
        """The submit endpoint rejects with HTTP 422 when there is no
        outstanding assignment, rather than silently no-op'ing — this is
        the security hardening from v2: the assigning provider must come
        from a server-side row, not the request body."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ) as mock_json_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_nt_objects:
            mock_service.get_outstanding_row.return_value = None
            captured = {}

            def capture(payload, status_code):
                captured["status_code"] = status_code
                captured["payload"] = payload
                return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            mock_json_cls.side_effect = capture
            api.submit_questionnaire()

        assert captured["status_code"] == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "No pending assignment" in captured["payload"]["error"]
        mock_service.mark_completed.assert_not_called()
        # Defense in depth: no DB I/O past the early check
        mock_nt_objects.filter.assert_not_called()

    def test_submit_returns_422_when_row_has_no_assigning_provider(self):
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ) as mock_json_cls:
            row = MagicMock()
            row.assigning_provider = None
            mock_service.get_outstanding_row.return_value = row
            captured = {}

            def capture(payload, status_code):
                captured["status_code"] = status_code
                captured["payload"] = payload
                return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            mock_json_cls.side_effect = capture
            api.submit_questionnaire()

        assert captured["status_code"] == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "missing an assigning provider" in captured["payload"]["error"]
        mock_service.mark_completed.assert_not_called()

    def test_submit_returns_422_when_no_active_questionnaire_matches_name(self):
        """If the questionnaire_name on the outstanding row no longer matches
        an active Questionnaire (deactivated/renamed), fail closed with 422
        rather than building a QuestionnaireCommand off the client-supplied
        id from the request body."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ) as mock_json_cls:
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_q_objects.filter.return_value.first.return_value = None
            captured = {}

            def capture(payload, status_code):
                captured["status_code"] = status_code
                captured["payload"] = payload
                return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            mock_json_cls.side_effect = capture
            api.submit_questionnaire()

        assert captured["status_code"] == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "No active questionnaire" in captured["payload"]["error"]
        mock_service.mark_completed.assert_not_called()

    def _row_with_provider(self, staff_id: str) -> MagicMock:
        """Build a row mock whose assigning_provider is a CustomStaff-like
        object with the attributes submit_questionnaire reads."""
        row = MagicMock()
        provider = MagicMock(
            primary_practice_location=MagicMock(id=uuid.uuid4()), id=staff_id
        )
        row.assigning_provider = provider
        return row

    def test_submit_returns_empty_when_mark_completed_loses_race(self):
        """Race window: get_outstanding_row saw a row but another submission
        completed it before mark_completed ran. Don't emit duplicate effects."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ):
            mock_note_type_objects.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            mock_qc.return_value.questions = []
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 0

            result = api.submit_questionnaire()

        assert result == []
        # mark_completed was called with the new submitted_answers kwarg
        mark_call = mock_service.mark_completed.call_args
        assert mark_call.args == (patient_id, "PHQ-9")
        assert "submitted_answers" in mark_call.kwargs
        mock_service.unassign.assert_not_called()

    def test_mark_completed_does_not_run_if_effect_construction_raises(self):
        """The transactional guarantee: if any Effect constructor raises
        between the early get_one check and the mark_completed call, the DB
        write must NOT happen."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ) as mock_note_effect_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service:
            mock_note_type_objects.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)

            # Simulate the constructor accepting the call but .create()
            # raising — mimics a server-side validation error surfaced when
            # the effect is built.
            note_effect = MagicMock()
            note_effect.create.side_effect = ValueError("invalid note shape")
            mock_note_effect_cls.return_value = note_effect

            mock_qc_cls.return_value.questions = []

            with pytest.raises(ValueError):
                api.submit_questionnaire()

        # The crucial assertion — the assignment row is NOT stamped completed.
        mock_service.mark_completed.assert_not_called()

    def test_submit_creates_note_and_marks_assignment_completed(self):
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ) as mock_note_effect_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ) as mock_json_cls:
            mock_note_type_objects.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            note_effect = MagicMock()
            note_effect.create.return_value = MagicMock(type=EffectType.CREATE_NOTE)
            mock_note_effect_cls.return_value = note_effect

            q1 = MagicMock(id="q1", type=ResponseOption.TYPE_TEXT)
            qc = MagicMock(questions=[q1])
            qc.originate.return_value = MagicMock()
            qc.edit.return_value = MagicMock()
            qc.commit.return_value = MagicMock()
            mock_qc_cls.return_value = qc

            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1
            mock_json_cls.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            result = api.submit_questionnaire()

        # Note create + originate + edit + commit + JSON response
        assert len(result) == 5
        q1.add_response.assert_called_once_with(text="ok")
        # The row is stamped completed with submitted_answers snapshotted.
        mark_call = mock_service.mark_completed.call_args
        assert mark_call.args == (patient_id, "PHQ-9")
        assert mark_call.kwargs["submitted_answers"] == [
            {"question_id": "q1", "question_type": "TEXT", "answer": "ok"}
        ]
        mock_service.unassign.assert_not_called()
        assert qc.originate.called
        assert qc.edit.called
        assert qc.commit.called

    def test_submit_reuses_existing_daily_note_when_resolve_returns_reuse(self):
        """Bundling path: when DailyNoteService says reuse the day's note,
        NoteEffect.create() is NOT emitted — the QuestionnaireCommand is
        layered onto the existing note instead. This is the difference
        between a Patient Portal Form bundle (multiple submissions, one note)
        and the DATA fallback (one note per submission)."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ) as mock_note_effect_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ) as mock_json_cls:
            mock_note_type_objects.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            # Reuse path: resolve returns (existing_uuid, True)
            reused_uuid = uuid.uuid4()
            mock_daily.resolve.return_value = (reused_uuid, True)

            qc = MagicMock(questions=[])
            qc.originate.return_value = MagicMock()
            qc.edit.return_value = MagicMock()
            qc.commit.return_value = MagicMock()
            mock_qc_cls.return_value = qc

            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1
            mock_json_cls.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

            result = api.submit_questionnaire()

        # No NoteEffect at all when reusing the day's bundle note
        mock_note_effect_cls.assert_not_called()
        # Just originate + edit + commit + JSON response (no note create)
        assert len(result) == 4
        # QuestionnaireCommand was targeted at the reused note's UUID
        assert mock_qc_cls.call_args.kwargs["note_uuid"] == str(reused_uuid)

    def test_submit_bundles_when_patient_portal_form_note_type_exists(self):
        """When the proper note type is configured, resolve is called with
        bundle=True so same-day submissions consolidate into one note."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ) as mock_note_effect_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ):
            # First filter (Patient Portal Form) returns a real UUID — bundle path
            mock_note_type_objects.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_qc_cls.return_value.questions = []
            mock_note_effect_cls.return_value = MagicMock()
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1

            api.submit_questionnaire()

        # DailyNoteService.resolve was invoked with bundle=True
        assert mock_daily.resolve.call_args.kwargs["bundle"] is True
        # Note title uses the daily-bundle format
        title = mock_note_effect_cls.call_args.kwargs["title"]
        assert title.startswith("Patient portal forms - ")

    def test_submit_does_not_bundle_when_falling_back_to_data_import(self):
        """When the Patient Portal Form note type is missing, the plugin
        falls back to DATA — and DATA notes are one-shot writes, so
        bundle=False is passed to resolve and the title reverts to the
        per-questionnaire format."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_note_type_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ) as mock_note_effect_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ):
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
            # First NoteType.filter() (for "Patient Portal Form") returns None —
            # second filter (for DATA category) returns a valid id.
            call_sequence = iter([None, str(uuid.uuid4())])

            def filter_side_effect(*args, **kwargs):
                chain = MagicMock()
                if "name" in kwargs:
                    chain.values_list.return_value.first.return_value = next(call_sequence)
                else:
                    # category=NoteTypeCategories.DATA path
                    chain.order_by.return_value.values_list.return_value.first.return_value = next(call_sequence)
                return chain

            mock_note_type_objects.filter.side_effect = filter_side_effect
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_qc_cls.return_value.questions = []
            mock_note_effect_cls.return_value = MagicMock()
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1

            api.submit_questionnaire()

        # Bundling disabled when falling back to DATA
        assert mock_daily.resolve.call_args.kwargs["bundle"] is False
        # Per-questionnaire title preserved
        title = mock_note_effect_cls.call_args.kwargs["title"]
        assert "submitted via patient app" in title

    def test_submit_handles_radio_and_checkbox_answers(self):
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        api = self._api(
            patient_id,
            staff_id,
            [
                {"question_id": "q-radio", "question_type": "RADIO", "answer": "opt1"},
                {
                    "question_id": "q-check",
                    "question_type": "CHECKBOX",
                    "answer": ["optA", "optB"],
                },
            ],
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_nt, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ):
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_nt.filter.return_value.values_list.return_value.first.return_value = str(
                uuid.uuid4()
            )
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())

            opt1 = MagicMock(dbid="opt1")
            radio_q = MagicMock(id="q-radio", type=ResponseOption.TYPE_RADIO)
            radio_q.options = [opt1]

            optA = MagicMock(dbid="optA")
            optB = MagicMock(dbid="optB")
            check_q = MagicMock(id="q-check", type=ResponseOption.TYPE_CHECKBOX)
            check_q.options = [optA, optB]

            qc = MagicMock(questions=[radio_q, check_q])
            mock_qc_cls.return_value = qc
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1

            api.submit_questionnaire()

        radio_q.add_response.assert_called_once_with(option=opt1)
        assert check_q.add_response.call_count == 2
        assert call(option=optA, selected=True) in check_q.add_response.call_args_list
        assert call(option=optB, selected=True) in check_q.add_response.call_args_list

    def test_submit_ignores_body_questionnaire_id_and_uses_server_resolved_id(self):
        """Security regression: the QuestionnaireCommand's questionnaire_id
        must come from the active Questionnaire matching the (validated)
        questionnaire_name, not from the request body. Otherwise a patient
        could pair their legit questionnaire_name with an unrelated
        questionnaire_id and produce a command structured under the wrong
        questionnaire."""
        patient_id = str(uuid.uuid4())
        staff_id = str(uuid.uuid4())
        attacker_supplied_id = str(uuid.uuid4())
        server_resolved_id = uuid.uuid4()

        api = _build_patient_api(
            patient_id=patient_id,
            body={
                "questionnaire_id": attacker_supplied_id,
                "questionnaire_name": "PHQ-9",
                "assigning_staff_id": staff_id,
                "questions_and_answers": [
                    {"question_id": "q1", "question_type": "TEXT", "answer": "ok"}
                ],
            },
        )

        with patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteType.objects"
        ) as mock_nt, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.NoteEffect"
        ), patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireCommand"
        ) as mock_qc_cls, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.Questionnaire.objects"
        ) as mock_q_objects, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.DailyNoteService"
        ) as mock_daily, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.QuestionnaireAssignmentService"
        ) as mock_service, patch(
            "patient_portal_forms.protocols.patient_portal_forms_api.JSONResponse"
        ):
            mock_nt.filter.return_value.values_list.return_value.first.return_value = str(uuid.uuid4())
            mock_q_objects.filter.return_value.first.return_value = MagicMock(id=server_resolved_id)
            mock_daily.resolve.return_value = (uuid.uuid4(), False)
            mock_qc_cls.return_value.questions = []
            mock_service.get_outstanding_row.return_value = self._row_with_provider(staff_id)
            mock_service.mark_completed.return_value = 1

            api.submit_questionnaire()

        # The lookup was scoped to the validated name and active status, NOT
        # to the body-supplied questionnaire_id.
        filter_kwargs = mock_q_objects.filter.call_args.kwargs
        assert filter_kwargs == {"name": "PHQ-9", "status": "AC"}

        # QuestionnaireCommand was built with the server-resolved id, not the
        # attacker-supplied one from the request body.
        passed_id = mock_qc_cls.call_args.kwargs["questionnaire_id"]
        assert passed_id == str(server_resolved_id)
        assert passed_id != attacker_supplied_id


# ----- Template encoding regression (carried over) --------------------------


class TestPatientFillOutQuestionnaireTemplate:
    """Template-rendering tests for patient_fill_out_questionnaire.html."""

    @staticmethod
    def _render(questionnaire_name: str) -> str:
        import django
        from django.conf import settings
        from django.template.engine import Engine
        from pathlib import Path

        if not settings.configured:
            settings.configure(DEBUG=False, USE_L10N=False, INSTALLED_APPS=[])
            django.setup()

        tpl_dir = Path(__file__).resolve().parents[2] / "patient_portal_forms"
        engine = Engine(dirs=[str(tpl_dir)])
        return engine.render_to_string(
            str(tpl_dir / "templates/patient_fill_out_questionnaire.html"),
            context={
                "questionnaire": {"id": "qid", "name": questionnaire_name, "questions": []},
                "due_date": "2026-01-01",
                "patient_id": "pid",
                "assigning_provider_id": "spid",
            },
        )

    @pytest.mark.parametrize(
        "name",
        [
            "Hearing & Sight Test",     # ampersand — customer-reported bug
            "Risk <Assessment>",        # angle brackets
            'Patient "Intake" Form',    # double quotes
            "Driver's Health Check",    # single quote / apostrophe
            "Path\\to\\form",           # backslash
            "Plain Questionnaire",      # control: no special chars
        ],
    )
    def test_questionnaire_name_round_trips_through_js(self, name):
        """The questionnaire name must reach the submission payload as the
        literal string. The submit endpoint looks up the assigned questionnaire
        by exact name match, so any encoding artifact in transit breaks the
        match (original report was for '&' → '&amp;')."""
        output = self._render(name)

        js_line = next(
            line for line in output.splitlines() if "questionnaire_name:" in line
        )

        assert "&amp;" not in js_line
        assert "&lt;" not in js_line
        assert "&gt;" not in js_line
        assert "&quot;" not in js_line
        assert "&#" not in js_line

        value_literal = js_line.split("questionnaire_name:", 1)[1].strip().rstrip(",")
        assert json.loads(value_literal) == name
