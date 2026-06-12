"""Unit tests for ExamChartingAPI routes.

These tests exercise the route handlers directly, bypassing the SimpleAPI
dispatcher — we're verifying that the right template is rendered with the
right content type and that finalize emits the right effects, not the
framework wiring.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from exam_chart_app.api import exam_api
from exam_chart_app.api.exam_api import ExamChartingAPI


def _make_api(
    query: dict | None = None,
    json_body: dict | None = None,
    secrets: dict | None = None,
) -> ExamChartingAPI:
    api_obj = ExamChartingAPI.__new__(ExamChartingAPI)
    api_obj.request = MagicMock()
    api_obj.request.query_params = query or {}
    api_obj.request.json = MagicMock(return_value=json_body if json_body is not None else {})
    api_obj.secrets = secrets or {}
    return api_obj


@patch("exam_chart_app.api.exam_api.render_to_string")
def test_get_css_returns_text_css_response(mock_render):
    exam_api._STATIC_CACHE.clear()
    mock_render.return_value = "body { color: red; }"
    responses = _make_api().get_exam_css()
    assert len(responses) == 1
    response = responses[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get("Content-Type", "").startswith("text/css")
    assert response.content == b"body { color: red; }"
    mock_render.assert_called_once_with("templates/exam.css")


@patch("exam_chart_app.api.exam_api.render_to_string")
def test_get_js_returns_text_javascript_response(mock_render):
    """exam.js is authored as multiple chunks and served as one bundle.
    The handler should request every chunk in `_EXAM_JS_PARTS` order
    and concatenate them into the response body."""
    exam_api._STATIC_CACHE.clear()
    # Make every render_to_string call return a distinct token so we can
    # verify both the call count + the order is correct.
    mock_render.side_effect = [f"/*chunk-{i}*/\n" for i in range(len(exam_api._EXAM_JS_PARTS))]
    responses = _make_api().get_exam_js()
    assert len(responses) == 1
    response = responses[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get("Content-Type", "").startswith("text/javascript")
    expected = "".join(f"/*chunk-{i}*/\n" for i in range(len(exam_api._EXAM_JS_PARTS))).encode()
    assert response.content == expected
    assert mock_render.call_count == len(exam_api._EXAM_JS_PARTS)
    # Confirm the chunk order matches the declared sequence.
    requested = [call.args[0] for call in mock_render.call_args_list]
    assert requested == list(exam_api._EXAM_JS_PARTS)


@patch("exam_chart_app.api.exam_api.render_to_string")
def test_static_assets_are_cached_after_first_call(mock_render):
    """Second call returns the same bytes without re-rendering from disk."""
    exam_api._STATIC_CACHE.clear()
    mock_render.return_value = "body { color: red; }"
    first = _make_api().get_exam_css()[0]
    second = _make_api().get_exam_css()[0]
    assert first.content == second.content == b"body { color: red; }"
    mock_render.assert_called_once_with("templates/exam.css")


@patch("exam_chart_app.api.exam_api.get_hpi_template")
def test_get_templates_returns_hpi_for_picked_code(mock_get_hpi):
    mock_get_hpi.return_value = "gerd hpi"
    responses = _make_api(query={"code": "K21.9"}).get_templates()
    body = json.loads(responses[0].content.decode())
    assert responses[0].status_code == HTTPStatus.OK
    assert body == {"hpi": "gerd hpi"}
    mock_get_hpi.assert_called_once_with("K21.9")


@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_emits_both_commands_when_rfv_and_hpi_present(mock_rfv, mock_hpi):
    mock_rfv.return_value.originate.return_value = "RFV_EFFECT"
    mock_hpi.return_value.originate.return_value = "HPI_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"coding": {"code": "K21.9", "system": "...", "display": "GERD"}, "comment": ""},
        "hpi": {"narrative": "Patient reports reflux symptoms."},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body == {
        "success": True,
        "effects": {"rfv": True, "hpi": True, "ros": False, "pe": False,
                    "diagnose_count": 0, "assess_count": 0, "plan_count": 0,
                    "lab_count": 0, "imaging_count": 0,
                    "prescribe_count": 0, "refer_count": 0, "goal_count": 0, "plan_item_count": 0, "follow_up_count": 0},
    }
    mock_rfv.assert_called_once()
    mock_hpi.assert_called_once()


@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_400_when_rfv_missing(mock_rfv, mock_hpi):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"coding": None, "comment": ""},
        "hpi": {"narrative": "..."},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "rfv"
    mock_rfv.assert_not_called()
    mock_hpi.assert_not_called()


@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_400_when_note_uuid_missing(mock_rfv, mock_hpi):
    payload = {"rfv": {"comment": "x"}, "hpi": {"narrative": "x"}}
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    mock_rfv.assert_not_called()
    mock_hpi.assert_not_called()


@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_skips_hpi_when_narrative_empty(mock_rfv, mock_hpi):
    mock_rfv.return_value.originate.return_value = "RFV_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "hpi": {"narrative": "   "},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body == {
        "success": True,
        "effects": {"rfv": True, "hpi": False, "ros": False, "pe": False,
                    "diagnose_count": 0, "assess_count": 0, "plan_count": 0,
                    "lab_count": 0, "imaging_count": 0,
                    "prescribe_count": 0, "refer_count": 0, "goal_count": 0, "plan_item_count": 0, "follow_up_count": 0},
    }
    mock_rfv.assert_called_once()
    mock_hpi.assert_not_called()


@patch("exam_chart_app.api.exam_api.find_questionnaires")
def test_list_questionnaires_returns_ros_and_pe(mock_find):
    ros_a = MagicMock(id="r1", code="ROS-B")
    ros_a.name = "Brief ROS"
    ros_b = MagicMock(id="r2", code="ROS-S")
    ros_b.name = "Standard ROS"
    pe_a = MagicMock(id="p1", code="PE-S")
    pe_a.name = "Standard Physical Exam"
    mock_find.side_effect = [[ros_a, ros_b], [pe_a]]

    responses = _make_api().list_questionnaires()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body["ros"] == [
        {"id": "r1", "name": "Brief ROS", "code": "ROS-B"},
        {"id": "r2", "name": "Standard ROS", "code": "ROS-S"},
    ]
    assert body["pe"] == [{"id": "p1", "name": "Standard Physical Exam", "code": "PE-S"}]
    assert mock_find.call_count == 2


@patch("exam_chart_app.api.exam_api.get_questionnaire_detail")
def test_get_questionnaire_by_id_returns_questions(mock_detail):
    mock_detail.return_value = {
        "id": "r1", "name": "Brief ROS", "code": "ROS-B", "code_system": "canvas",
        "questions": [
            {"id": 1, "label": "Constitutional", "type": "SING",
             "options": [{"name": "Normal", "code": "N", "value": "normal"},
                         {"name": "Abnormal", "code": "AB", "value": "abnormal"}]},
        ],
    }
    responses = _make_api(query={"id": "r1"}).get_questionnaire_by_id()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body["name"] == "Brief ROS"
    assert len(body["questions"]) == 1


@patch("exam_chart_app.api.exam_api.get_questionnaire_detail")
def test_get_questionnaire_by_id_404_when_missing(mock_detail):
    mock_detail.return_value = None
    responses = _make_api(query={"id": "nope"}).get_questionnaire_by_id()
    assert responses[0].status_code == HTTPStatus.NOT_FOUND


def test_get_questionnaire_by_id_400_when_id_missing():
    responses = _make_api(query={}).get_questionnaire_by_id()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_emits_ros_and_pe_when_provided(mock_rfv, mock_hpi, mock_ros, mock_pe):
    ros_instance = MagicMock()
    pe_instance = MagicMock()
    mock_ros.return_value = ros_instance
    mock_pe.return_value = pe_instance
    # Question stubs — only `id` is exercised; responses iterate over command.questions.
    q1 = MagicMock(); q1.id = "1"
    q2 = MagicMock(); q2.id = "2"
    q3 = MagicMock(); q3.id = "3"
    ros_instance.questions = [q1, q2, q3]
    p1 = MagicMock(); p1.id = "10"
    pe_instance.questions = [p1]

    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "hpi": {"narrative": "Patient HPI text."},
        "ros": {
            "questionnaire_id": "ros-uuid",
            "responses": {"1": "normal", "2": "abnormal"},
            "skipped": ["3"],
            "narrative": "Otherwise unremarkable.",
        },
        "pe": {
            "questionnaire_id": "pe-uuid",
            "responses": {"10": "normal"},
            "skipped": [],
            "narrative": "",
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body == {
        "success": True,
        "effects": {"rfv": True, "hpi": True, "ros": True, "pe": True,
                    "diagnose_count": 0, "assess_count": 0, "plan_count": 0,
                    "lab_count": 0, "imaging_count": 0,
                    "prescribe_count": 0, "refer_count": 0, "goal_count": 0, "plan_item_count": 0, "follow_up_count": 0},
    }

    mock_ros.assert_called_once()
    ros_call_kwargs = mock_ros.call_args.kwargs
    assert ros_call_kwargs["questionnaire_id"] == "ros-uuid"
    # `result` is no longer set on the command — the narrative now rides
    # a separate CommandMetadataCreateFormEffect; just verify the
    # command_uuid was minted up front so the metadata effect could
    # reference it.
    assert ros_call_kwargs["command_uuid"]
    ros_instance.set_question_enabled.assert_called_with("3", False)


@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_skips_ros_when_empty(mock_rfv, mock_hpi, mock_ros, mock_pe):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ros": {
            "questionnaire_id": "ros-uuid",
            "responses": {},
            "skipped": [],
            "narrative": "",
        },
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["ros"] is False
    mock_ros.assert_not_called()


@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_400_when_ros_questionnaire_id_missing_with_responses(mock_rfv, mock_hpi, mock_ros, mock_pe):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ros": {
            "responses": {"1": "normal"},
            "narrative": "",
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ros"
    mock_ros.assert_not_called()


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_emits_per_diagnosis_blocks(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
):
    mock_dx.return_value.originate.return_value = "DX_EFFECT"
    mock_assess.return_value.originate.return_value = "ASSESS_EFFECT"
    mock_plan.return_value.originate.return_value = "PLAN_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [
                {
                    "code": "K21.9", "display": "GERD",
                    "today_assessment": "Heartburn 3x/week",
                    "assessment": {"status": "stable", "narrative": "Improving."},
                    "plan": {"narrative": "Continue PPI."},
                },
                {
                    "code": "M25.561", "display": "Right knee pain",
                    "assessment": {"status": "deteriorated", "narrative": "Worse."},
                    "plan": {"narrative": "PT referral."},
                },
            ],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["diagnose_count"] == 2
    assert body["effects"]["assess_count"] == 2
    assert body["effects"]["plan_count"] == 2
    assert mock_dx.call_count == 2
    # First diagnosis: today_assessment populated
    dx0_kwargs = mock_dx.call_args_list[0].kwargs
    assert dx0_kwargs["icd10_code"] == "K21.9"
    assert dx0_kwargs["today_assessment"] == "Heartburn 3x/week"
    # Second diagnosis: no today_assessment kwarg (omitted)
    dx1_kwargs = mock_dx.call_args_list[1].kwargs
    assert dx1_kwargs["icd10_code"] == "M25.561"
    assert "today_assessment" not in dx1_kwargs
    assert mock_assess.call_count == 2
    assert mock_plan.call_count == 2


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_skips_empty_ap(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {"diagnoses": []},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["diagnose_count"] == 0
    assert body["effects"]["assess_count"] == 0
    assert body["effects"]["plan_count"] == 0
    mock_dx.assert_not_called()
    mock_assess.assert_not_called()
    mock_plan.assert_not_called()


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_diagnose_skips_entries_missing_code(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
):
    mock_dx.return_value.originate.return_value = "DX_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [
                {"code": "K21.9", "display": "GERD"},
                {"code": "", "display": "no-code junk"},
                {"display": "no-code junk 2"},
            ],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["diagnose_count"] == 1
    assert mock_dx.call_count == 1


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_assess_status_string_maps_to_enum(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
):
    mock_dx.return_value.originate.return_value = "DX_EFFECT"
    mock_assess.return_value.originate.return_value = "ASSESS_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [
                {
                    "code": "K21.9", "display": "GERD",
                    "assessment": {"status": "improved", "narrative": "doing well"},
                },
            ],
        },
    }
    _make_api(json_body=payload).finalize()
    assess_kwargs = mock_assess.call_args.kwargs
    from canvas_sdk.commands import AssessCommand
    assert assess_kwargs["status"] == AssessCommand.Status.IMPROVED


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_existing_condition_emits_assess_only_not_diagnose(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
):
    """When a diagnosis entry carries existing_condition_id, no
    DiagnoseCommand is emitted — only AssessCommand(condition_id=...).
    A new Condition row would have been a mistake; the patient already
    has it."""
    mock_assess.return_value.originate.return_value = "ASSESS_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [
                {
                    "code": "K21.9", "display": "GERD",
                    "existing_condition_id": "22222222-2222-2222-2222-222222222222",
                    "assessment": {"status": "stable", "narrative": "Doing well."},
                    "plan": {"narrative": "Continue PPI."},
                },
            ],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["diagnose_count"] == 0
    assert body["effects"]["assess_count"] == 1
    assert body["effects"]["plan_count"] == 1
    mock_dx.assert_not_called()
    mock_assess.assert_called_once()
    assess_kwargs = mock_assess.call_args.kwargs
    assert assess_kwargs["condition_id"] == "22222222-2222-2222-2222-222222222222"


@patch("exam_chart_app.api.exam_api.Condition")
def test_get_patient_conditions_returns_icd10_first(mock_cond_cls):
    """Prefers ICD-10 codings over other systems. Includes
    clinical_status in the response so the front-end can render it
    informationally even though the backend no longer filters on it."""
    icd_coding = MagicMock(code="K21.9", system="http://hl7.org/fhir/sid/icd-10-cm")
    icd_coding.display = "Gastro-esophageal reflux disease without esophagitis"
    snomed_coding = MagicMock(code="235595009", system="http://snomed.info/sct")
    snomed_coding.display = "GERD (snomed)"
    cond = MagicMock(id="cond-1", clinical_status="active")
    cond.codings.all.return_value = [snomed_coding, icd_coding]
    qs = MagicMock()
    qs.prefetch_related.return_value = [cond]
    mock_cond_cls.objects.filter.return_value = qs
    mock_cond_cls.objects.filter.return_value.count.return_value = 1

    api_obj = _make_api(query={"patient_id": "22222222-2222-2222-2222-222222222222"})
    responses = api_obj.get_patient_conditions()
    body = json.loads(responses[0].content.decode())
    assert body["conditions"] == [{
        "id": "cond-1",
        "code": "K21.9",
        "display": "Gastro-esophageal reflux disease without esophagitis",
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "clinical_status": "active",
    }]
    filter_kwargs = mock_cond_cls.objects.filter.call_args_list[0].kwargs
    assert filter_kwargs["patient__id"] == "22222222-2222-2222-2222-222222222222"
    assert filter_kwargs["entered_in_error__isnull"] is True
    # No clinical_status filter — Canvas's value varies and missing a
    # match here silently degrades the existing-condition flow.
    assert "clinical_status" not in filter_kwargs


@patch("exam_chart_app.api.exam_api.Condition")
def test_get_patient_conditions_falls_back_to_icd10_shape_when_no_icd_system(mock_cond_cls):
    """If no coding has an ICD-10 system URI, fall back to any coding
    whose code matches the ICD-10 letter-then-digit shape (e.g. 'N39.0').
    Canvas doesn't always stamp the system URI consistently."""
    odd_coding = MagicMock(code="N39.0", system="")
    odd_coding.display = "UTI"
    cond = MagicMock(id="cond-2", clinical_status="active")
    cond.codings.all.return_value = [odd_coding]
    qs = MagicMock()
    qs.prefetch_related.return_value = [cond]
    mock_cond_cls.objects.filter.return_value = qs
    mock_cond_cls.objects.filter.return_value.count.return_value = 1

    api_obj = _make_api(query={"patient_id": "22222222-2222-2222-2222-222222222222"})
    responses = api_obj.get_patient_conditions()
    body = json.loads(responses[0].content.decode())
    assert len(body["conditions"]) == 1
    assert body["conditions"][0]["code"] == "N39.0"


def test_get_patient_conditions_missing_patient_id_returns_empty():
    responses = _make_api(query={}).get_patient_conditions()
    body = json.loads(responses[0].content.decode())
    assert body == {"conditions": []}


@patch("exam_chart_app.api.exam_api.Condition")
def test_get_patient_conditions_invalid_uuid_returns_empty_without_querying(mock_cond_cls):
    """Patient.id is a UUIDField; a non-UUID query string would raise
    django.core.exceptions.ValidationError before the ORM filter runs
    and escape as an empty-body 500 + 48 MB traceback allocation
    (same pattern questionnaires.py:get_questionnaire_detail mitigates).
    Verify the gate short-circuits BEFORE the ORM is touched."""
    responses = _make_api(query={"patient_id": "not-a-uuid"}).get_patient_conditions()
    body = json.loads(responses[0].content.decode())
    assert body == {"conditions": []}
    mock_cond_cls.objects.filter.assert_not_called()


@patch("exam_chart_app.api.emitters.ReferCommand")
@patch("exam_chart_app.api.emitters.PrescribeCommand")
@patch("exam_chart_app.api.emitters.ImagingOrderCommand")
@patch("exam_chart_app.api.emitters.LabOrderCommand")
@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_emits_lab_imaging_prescribe_refer(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
    mock_lab, mock_imaging, mock_rx, mock_refer,
):
    mock_lab.return_value.originate.return_value = "LAB"
    mock_imaging.return_value.originate.return_value = "IMG"
    mock_rx.return_value.originate.return_value = "RX"
    mock_refer.return_value.originate.return_value = "REF"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [{"code": "K21.9", "display": "GERD"}],
            "orders": [
                {"type": "lab", "lab_partner": "p1", "tests": [{"order_code": "BMP"}],
                 "ordering_provider_key": "staff-1", "diagnosis_codes": ["K21.9"]},
                {"type": "imaging", "image_code": "XR Chest 2 Views",
                 "priority": "ROUTINE", "diagnosis_codes": ["K21.9"],
                 "ordering_provider_key": "staff-1"},
                {"type": "prescribe", "fdb_code": "153666",
                 "sig": "1 cap PO daily", "icd10_codes": ["K21.9"],
                 "prescriber_id": "staff-1",
                 "quantity_to_dispense": 30, "days_supply": 30, "refills": 0,
                 "representative_ndc": "00071-0941-23",
                 "ncpdp_quantity_qualifier_code": "C48542"},
                {"type": "refer",
                 "service_provider": {"first_name": "Jane", "last_name": "Doe",
                                       "specialty": "GI", "practice_name": "Apex GI"},
                 "clinical_question": "ASSISTANCE_WITH_ONGOING_MANAGEMENT",
                 "priority": "ROUTINE", "diagnosis_codes": ["K21.9"],
                 "notes_to_specialist": "Please evaluate GERD"},
            ],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["lab_count"] == 1
    assert body["effects"]["imaging_count"] == 1
    assert body["effects"]["prescribe_count"] == 1
    assert body["effects"]["refer_count"] == 1
    mock_lab.assert_called_once()
    mock_imaging.assert_called_once()
    mock_rx.assert_called_once()
    mock_refer.assert_called_once()
    lab_kwargs = mock_lab.call_args.kwargs
    assert lab_kwargs["lab_partner"] == "p1"
    assert lab_kwargs["tests_order_codes"] == ["BMP"]
    assert lab_kwargs["diagnosis_codes"] == ["K21.9"]
    img_kwargs = mock_imaging.call_args.kwargs
    from canvas_sdk.commands import ImagingOrderCommand as _ICmd
    assert img_kwargs["priority"] == _ICmd.Priority.ROUTINE
    rx_kwargs = mock_rx.call_args.kwargs
    assert rx_kwargs["fdb_code"] == "153666"
    assert rx_kwargs["type_to_dispense"] == {
        "representative_ndc": "00071-0941-23",
        "ncpdp_quantity_qualifier_code": "C48542",
    }
    refer_kwargs = mock_refer.call_args.kwargs
    from canvas_sdk.commands import ReferCommand as _RCmd
    assert refer_kwargs["priority"] == _RCmd.Priority.ROUTINE
    assert refer_kwargs["clinical_question"] == _RCmd.ClinicalQuestion.ASSISTANCE_WITH_ONGOING_MANAGEMENT


@patch("exam_chart_app.api.emitters.ReferCommand")
@patch("exam_chart_app.api.emitters.PrescribeCommand")
@patch("exam_chart_app.api.emitters.ImagingOrderCommand")
@patch("exam_chart_app.api.emitters.LabOrderCommand")
@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_orders_skips_unknown_type(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_dx, mock_assess, mock_plan,
    mock_lab, mock_imaging, mock_rx, mock_refer,
):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{"type": "nonsense"}]},
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["lab_count"] == 0
    assert body["effects"]["imaging_count"] == 0
    assert body["effects"]["prescribe_count"] == 0
    assert body["effects"]["refer_count"] == 0
    mock_lab.assert_not_called()
    mock_imaging.assert_not_called()
    mock_rx.assert_not_called()
    mock_refer.assert_not_called()


def _make_api_with_headers(headers: dict) -> ExamChartingAPI:
    api_obj = ExamChartingAPI.__new__(ExamChartingAPI)
    api_obj.request = MagicMock()
    api_obj.request.headers = headers
    api_obj.request.query_params = {}
    return api_obj


def test_get_me_returns_anonymous_when_headers_missing():
    responses = _make_api_with_headers({}).get_me()
    body = json.loads(responses[0].content.decode())
    assert body == {"id": "", "type": "", "first_name": "", "last_name": ""}


@patch("canvas_sdk.v1.data.Staff")
def test_get_me_resolves_staff_name_when_logged_in(mock_staff):
    s = MagicMock()
    s.first_name = "Jane"
    s.last_name = "Doe"
    mock_staff.objects.get.return_value = s
    headers = {
        "canvas-logged-in-user-id": "staff-1",
        "canvas-logged-in-user-type": "Staff",
    }
    responses = _make_api_with_headers(headers).get_me()
    body = json.loads(responses[0].content.decode())
    assert body == {
        "id": "staff-1", "type": "Staff", "first_name": "Jane", "last_name": "Doe",
    }


@patch("exam_chart_app.api.emitters.FollowUpCommand")
@patch("exam_chart_app.api.emitters.GoalCommand")
@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_emits_goal_planitem_followup(
    mock_rfv, mock_plan, mock_goal, mock_followup,
):
    mock_goal.return_value.originate.return_value = "GOAL"
    mock_plan.return_value.originate.return_value = "PLAN"
    mock_followup.return_value.originate.return_value = "FU"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [],
            "orders": [
                {"type": "goal", "goal_statement": "Lose 10 lbs",
                 "due_date": "2026-12-31", "priority": "HIGH",
                 "progress": "starting now"},
                {"type": "plan_item", "narrative": "Increase exercise to 30 min/day"},
                {"type": "follow_up", "requested_date": "2026-06-01",
                 "reason_for_visit": "Weight check", "comment": "3-month follow up"},
            ],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["goal_count"] == 1
    assert body["effects"]["plan_item_count"] == 1
    assert body["effects"]["follow_up_count"] == 1

    goal_kwargs = mock_goal.call_args.kwargs
    assert goal_kwargs["goal_statement"] == "Lose 10 lbs"
    from datetime import date as _date
    assert goal_kwargs["due_date"] == _date(2026, 12, 31)
    from canvas_sdk.commands import GoalCommand as _GCmd
    assert goal_kwargs["priority"] == _GCmd.Priority.HIGH
    assert goal_kwargs["progress"] == "starting now"

    plan_kwargs = mock_plan.call_args.kwargs
    assert plan_kwargs["narrative"] == "Increase exercise to 30 min/day"

    fu_kwargs = mock_followup.call_args.kwargs
    assert fu_kwargs["requested_date"] == _date(2026, 6, 1)
    assert fu_kwargs["reason_for_visit"] == "Weight check"
    assert fu_kwargs["comment"] == "3-month follow up"


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_skips_empty_plan_item(mock_rfv, mock_plan):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{"type": "plan_item", "narrative": "  "}]},
    }
    responses = _make_api(json_body=payload).finalize()
    body = json.loads(responses[0].content.decode())
    assert body["effects"]["plan_item_count"] == 0
    mock_plan.assert_not_called()


# ----- Checkpoint 8: /exam/state + /exam/finalize finalized flag -----


@patch("exam_chart_app.api.exam_api.was_ever_finalized")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_get_state_returns_empty_for_no_saved_state(mock_get, mock_was):
    mock_get.return_value = ({}, False)
    mock_was.return_value = False
    api_obj = _make_api(query={"note_uuid": "11111111-1111-1111-1111-111111111111"})
    responses = api_obj.get_state()
    body = json.loads(responses[0].content.decode())
    assert responses[0].status_code == HTTPStatus.OK
    assert body == {"state": {}, "finalized": False, "has_chart_commands": False}


@patch("exam_chart_app.api.exam_api.was_ever_finalized")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_get_state_returns_saved_state_with_finalized_flag(mock_get, mock_was):
    mock_get.return_value = ({"rfv": {"comment": "x"}}, True)
    mock_was.return_value = True
    api_obj = _make_api(query={"note_uuid": "11111111-1111-1111-1111-111111111111"})
    responses = api_obj.get_state()
    body = json.loads(responses[0].content.decode())
    assert body == {
        "state": {"rfv": {"comment": "x"}},
        "finalized": True,
        "has_chart_commands": True,
    }


@patch("exam_chart_app.api.exam_api.was_ever_finalized")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_get_state_flags_orphan_commands_when_this_plugin_finalized_before(
    mock_get, mock_was,
):
    """Empty draft + THIS plugin previously finalized the note → frontend
    renders the 'commands exist but plugin draft was cleared' banner."""
    mock_get.return_value = ({}, False)
    mock_was.return_value = True
    api_obj = _make_api(query={"note_uuid": "11111111-1111-1111-1111-111111111111"})
    responses = api_obj.get_state()
    body = json.loads(responses[0].content.decode())
    assert body == {"state": {}, "finalized": False, "has_chart_commands": True}
    mock_was.assert_called_once_with("11111111-1111-1111-1111-111111111111")


@patch("exam_chart_app.api.exam_api.was_ever_finalized")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_get_state_no_orphan_banner_when_only_sibling_plugin_finalized(
    mock_get, mock_was,
):
    """Another plugin finalized commands on this note, but THIS plugin
    (exam) has never finalized. The frontend must NOT show the
    orphan-commands banner — that's the bug we're fixing."""
    mock_get.return_value = ({}, False)
    mock_was.return_value = False
    api_obj = _make_api(query={"note_uuid": "11111111-1111-1111-1111-111111111111"})
    responses = api_obj.get_state()
    body = json.loads(responses[0].content.decode())
    assert body["has_chart_commands"] is False


def test_get_state_400_when_note_uuid_invalid():
    responses = _make_api(query={"note_uuid": "not-a-uuid"}).get_state()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@patch("exam_chart_app.api.exam_api.set_draft")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_save_state_persists_blob(mock_get, mock_set):
    # get_draft is consulted by the finalized-note guard (see
    # test_save_state_409_when_note_already_finalized); mock it to the
    # not-yet-finalized state so this success-path test stays
    # isolated from AttributeHub query semantics.
    mock_get.return_value = ({}, False)
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": {"rfv": {"comment": "Annual visit"}},
    }
    responses = _make_api(json_body=payload).save_state()
    body = json.loads(responses[0].content.decode())
    assert body == {"success": True}
    mock_set.assert_called_once_with(
        "11111111-1111-1111-1111-111111111111",
        {"rfv": {"comment": "Annual visit"}},
    )


@patch("exam_chart_app.api.exam_api.set_draft")
def test_save_state_400_when_state_not_object(mock_set):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": "not-an-object",
    }
    responses = _make_api(json_body=payload).save_state()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    mock_set.assert_not_called()


@patch("exam_chart_app.api.exam_api.set_draft")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_save_state_swallows_get_draft_db_error_and_proceeds(mock_get, mock_set):
    """A transient DB error from the get_draft finalized-check should be
    swallowed (logged for Sentry via log.exception) and treated as
    'not finalized' — control falls through to set_draft. Mirrors the
    finalize() narrow-catch pattern."""
    from django.db import OperationalError
    mock_get.side_effect = OperationalError("connection lost")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": {"rfv": {"comment": "Annual visit"}},
    }
    responses = _make_api(json_body=payload).save_state()
    # The DB read failure didn't 500; control reached set_draft.
    assert responses[0].status_code == HTTPStatus.OK
    mock_set.assert_called_once_with(
        "11111111-1111-1111-1111-111111111111",
        {"rfv": {"comment": "Annual visit"}},
    )


@patch("exam_chart_app.api.exam_api.set_draft")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_save_state_propagates_get_draft_programming_bug(mock_get, mock_set):
    """Locks the narrow-catch invariant: non-DB-class exceptions from
    get_draft (AttributeError on a renamed AttributeHub attr, TypeError
    from a wrong return shape, etc.) must propagate as 500 + Sentry —
    not be silently swallowed alongside DB transients."""
    import pytest
    mock_get.side_effect = AttributeError("AttributeHub.something renamed")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": {"rfv": {"comment": "Annual visit"}},
    }
    with pytest.raises(AttributeError):
        _make_api(json_body=payload).save_state()
    mock_set.assert_not_called()


@patch("exam_chart_app.api.exam_api.set_draft")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_save_state_409_when_note_already_finalized(mock_get, mock_set):
    """Backend defense-in-depth: a stale tab (or any direct client call)
    that POSTs to /exam/state/save after the note has been finalized
    must get a 409 — silently overwriting the draft would mislead the
    provider into thinking edits are reaching the chart when they
    aren't. The frontend's _lockFormForFinalized prevents this from
    happening through the form, but the backend guard catches the
    bypass case."""
    mock_get.return_value = ({"rfv": {"comment": "x"}}, True)  # finalized=True
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": {"rfv": {"comment": "post-finalize edit attempt"}},
    }
    responses = _make_api(json_body=payload).save_state()
    assert responses[0].status_code == HTTPStatus.CONFLICT
    body = json.loads(responses[0].content.decode())
    assert "finalized" in body["errors"][0]["message"].lower()
    mock_set.assert_not_called()


@patch("exam_chart_app.api.exam_api.mark_ever_finalized")
@patch("exam_chart_app.api.exam_api.mark_finalized")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_marks_state_finalized(mock_rfv, mock_hpi, mock_mark, mock_ever):
    """Both the draft `finalized` flag AND the persistent `meta:` marker
    must be set so the orphan-commands banner can fire after a
    delete/undelete cycle wipes the draft row."""
    mock_rfv.return_value.originate.return_value = "RFV_EFFECT"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    mock_mark.assert_called_once_with("11111111-1111-1111-1111-111111111111")
    mock_ever.assert_called_once_with("11111111-1111-1111-1111-111111111111")


@patch("exam_chart_app.api.exam_api.set_narrative")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_flushes_buffered_narratives_after_all_sections_succeed(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_set_narrative,
):
    """On the success path, every buffered narrative is flushed via
    set_narrative() AFTER all per-section emitters return without error."""
    mock_rfv.return_value.originate.return_value = "RFV_EFFECT"
    ros_instance = mock_ros.return_value
    ros_instance.questions = []
    pe_instance = mock_pe.return_value
    pe_instance.questions = []

    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ros": {
            "questionnaire_id": "ros-uuid",
            "responses": {},
            "skipped": [],
            "narrative": "ROS narrative text.",
        },
        "pe": {
            "questionnaire_id": "pe-uuid",
            "responses": {},
            "skipped": [],
            "narrative": "PE narrative text.",
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK

    # Both ROS + PE narratives flushed via set_narrative(command_uuid, text).
    # command_uuid is freshly minted inside each _emit_questionnaire call;
    # assert on the narrative text only, then check that both UUIDs match
    # what was passed to the respective Command constructors.
    assert mock_set_narrative.call_count == 2
    narratives_written = {c.args[1] for c in mock_set_narrative.call_args_list}
    assert narratives_written == {"ROS narrative text.", "PE narrative text."}

    ros_uuid = mock_ros.call_args.kwargs["command_uuid"]
    pe_uuid = mock_pe.call_args.kwargs["command_uuid"]
    uuids_written = {c.args[0] for c in mock_set_narrative.call_args_list}
    assert uuids_written == {ros_uuid, pe_uuid}


@patch("exam_chart_app.api.exam_api.set_narrative")
@patch("exam_chart_app.api.exam_api.PhysicalExamCommand")
@patch("exam_chart_app.api.exam_api.ReviewOfSystemsCommand")
@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_does_not_flush_narratives_when_later_section_fails(
    mock_rfv, mock_hpi, mock_ros, mock_pe, mock_set_narrative,
):
    """The post-gate flush invariant: a later-section failure must abort
    finalize with NO AttributeHub side-effects. ROS succeeds (buffering a
    narrative) but PE's constructor raises ValueError — set_narrative must
    not be called for either section."""
    mock_rfv.return_value.originate.return_value = "RFV_EFFECT"
    ros_instance = mock_ros.return_value
    ros_instance.questions = []
    # Force PE's _emit_questionnaire path into its (ValueError, TypeError)
    # except branch by raising on Command instantiation.
    mock_pe.side_effect = ValueError("simulated PE construction failure")

    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ros": {
            "questionnaire_id": "ros-uuid",
            "responses": {},
            "skipped": [],
            "narrative": "ROS narrative text.",
        },
        "pe": {
            "questionnaire_id": "pe-uuid",
            "responses": {},
            "skipped": [],
            "narrative": "PE narrative text.",
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "pe"
    mock_set_narrative.assert_not_called()


@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_rejects_imaging_without_ordering_provider(mock_rfv):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
        "ap": {
            "diagnoses": [],
            "orders": [{"type": "imaging", "image_code": "XR Chest"}],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.imaging"
    assert body["errors"][0]["field"] == "ordering_provider_key"


@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_rejects_refer_without_notes_to_specialist(mock_rfv):
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {
            "diagnoses": [],
            "orders": [{
                "type": "refer",
                "service_provider": {"first_name": "Jane", "last_name": "Doe"},
                "clinical_question": "ASSISTANCE_WITH_ONGOING_MANAGEMENT",
                "priority": "ROUTINE",
            }],
        },
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.refer"


# ----- _dispatch_response branch coverage -----


from exam_chart_app.api.emitters import _dispatch_response


def test_dispatch_response_mult_selects_matching_options_by_value():
    opt_a = MagicMock()
    opt_a.value = "1"
    opt_a.code = "a-code"
    opt_b = MagicMock()
    opt_b.value = "2"
    opt_b.code = "b-code"
    question = MagicMock()
    question.type = "MULT"
    question.options = [opt_a, opt_b]
    _dispatch_response(question, ["1"])
    question.add_response.assert_called_once_with(opt_a, selected=True)


def test_dispatch_response_sing_matches_by_code_returns_after_first():
    opt_a = MagicMock()
    opt_a.value = ""
    opt_a.code = "yes"
    opt_b = MagicMock()
    opt_b.value = ""
    opt_b.code = "yes"  # duplicate to confirm we stop after the first match
    question = MagicMock()
    question.type = "SING"
    question.options = [opt_a, opt_b]
    _dispatch_response(question, "yes")
    question.add_response.assert_called_once_with(opt_a)


def test_dispatch_response_txt_passes_text_kwarg():
    question = MagicMock()
    question.type = "TXT"
    _dispatch_response(question, ["patient reports cough"])
    question.add_response.assert_called_once_with(text="patient reports cough")


def test_dispatch_response_int_parses_integer():
    question = MagicMock()
    question.type = "INT"
    _dispatch_response(question, ["42"])
    question.add_response.assert_called_once_with(integer=42)


def test_dispatch_response_int_silently_drops_non_numeric():
    question = MagicMock()
    question.type = "INT"
    _dispatch_response(question, ["not-a-number"])
    question.add_response.assert_not_called()


def test_dispatch_response_empty_values_is_noop():
    question = MagicMock()
    question.type = "TXT"
    _dispatch_response(question, [None, "", None])
    question.add_response.assert_not_called()


# ----- _parse_iso_date / _str_list helpers -----


from exam_chart_app.api.emitters import _parse_iso_date, _str_list
from datetime import date as _date


def test_parse_iso_date_returns_date_for_valid_string():
    assert _parse_iso_date("2026-06-01") == _date(2026, 6, 1)


def test_parse_iso_date_returns_none_for_non_string():
    assert _parse_iso_date(None) is None
    assert _parse_iso_date(20260601) is None


def test_parse_iso_date_returns_none_for_empty_or_invalid():
    assert _parse_iso_date("") is None
    assert _parse_iso_date("   ") is None
    assert _parse_iso_date("06/01/2026") is None


def test_str_list_returns_empty_for_non_list():
    assert _str_list(None) == []
    assert _str_list("not a list") == []
    assert _str_list({"a": 1}) == []


def test_str_list_strips_and_filters_blanks():
    assert _str_list([" a ", "", None, "b", "  "]) == ["a", "b", ""]


# ----- /exam/state/save error paths (incl. DraftTooLargeError → 413) -----


def test_save_state_400_when_json_parse_fails():
    api_obj = _make_api(json_body={})
    api_obj.request.json = MagicMock(side_effect=ValueError("bad json"))
    responses = api_obj.save_state()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_state_400_when_body_not_object():
    api_obj = _make_api(json_body=None)
    api_obj.request.json = MagicMock(return_value=["not", "an", "object"])
    responses = api_obj.save_state()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_save_state_400_when_note_uuid_invalid():
    responses = _make_api(json_body={"note_uuid": "not-a-uuid", "state": {}}).save_state()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@patch("exam_chart_app.api.exam_api.set_draft")
@patch("exam_chart_app.api.exam_api.get_draft")
def test_save_state_413_when_draft_too_large(mock_get, mock_set):
    # get_draft is consulted by the finalized-note guard before set_draft
    # runs; mock to not-yet-finalized so this test exercises the
    # DraftTooLargeError → 413 path rather than getting blocked by the
    # 409 guard.
    mock_get.return_value = ({}, False)
    from exam_chart_app.data.draft_state import DraftTooLargeError
    mock_set.side_effect = DraftTooLargeError("1500000 bytes exceeds cap 1000000")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "state": {"big": "x"},
    }
    responses = _make_api(json_body=payload).save_state()
    assert responses[0].status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "state"
    assert "too large" in body["errors"][0]["message"].lower()


# ----- /exam/finalize body-validation paths -----


def test_finalize_400_when_json_parse_fails():
    api_obj = _make_api(json_body={})
    api_obj.request.json = MagicMock(side_effect=ValueError("bad json"))
    responses = api_obj.finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_finalize_400_when_body_not_object():
    api_obj = _make_api(json_body=None)
    api_obj.request.json = MagicMock(return_value=["bad"])
    responses = api_obj.finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_finalize_400_when_note_uuid_invalid():
    responses = _make_api(json_body={"note_uuid": "x"}).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


def test_finalize_400_when_rfv_key_absent_from_payload():
    """Distinct from `test_finalize_400_when_rfv_missing` above (which
    sends an explicit empty rfv object): here the `rfv` key isn't in
    the body at all."""
    responses = _make_api(json_body={
        "note_uuid": "11111111-1111-1111-1111-111111111111",
    }).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "rfv"


@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_uses_display_alone_when_no_code(mock_rfv):
    """rfv_text fallback: display present, code absent → display alone."""
    mock_rfv.return_value.originate.return_value = "RFV"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"coding": {"display": "Annual visit", "code": ""}},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    assert mock_rfv.call_args.kwargs["comment"] == "Annual visit"


@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_rfv_originate_raises(mock_rfv):
    mock_rfv.return_value.originate.side_effect = ValueError("validation failed")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "rfv"


@patch("exam_chart_app.api.exam_api.HistoryOfPresentIllnessCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_hpi_originate_raises(mock_rfv, mock_hpi):
    mock_rfv.return_value.originate.return_value = "RFV"
    mock_hpi.return_value.originate.side_effect = ValueError("hpi failed")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "hpi": {"narrative": "Reflux symptoms."},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "hpi"


# ----- Order emitter error paths (covers _emit_* exception branches) -----


@patch("exam_chart_app.api.emitters.LabOrderCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_lab_order_raises(mock_rfv, mock_lab):
    mock_lab.return_value.originate.side_effect = ValueError("lab boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "lab",
            "lab_partner": "lp-1",
            "ordering_provider_key": "staff-1",
            "tests": [{"order_code": "1234"}],
            "diagnosis_codes": ["K21.9"],
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.lab"


@patch("exam_chart_app.api.emitters.ImagingOrderCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_imaging_raises(mock_rfv, mock_imaging):
    mock_imaging.return_value.originate.side_effect = ValueError("img boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "imaging",
            "ordering_provider_key": "staff-1",
            "diagnosis_codes": ["K21.9"],
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.imaging"


@patch("exam_chart_app.api.emitters.PrescribeCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_prescribe_raises(mock_rfv, mock_rx):
    mock_rx.return_value.originate.side_effect = ValueError("rx boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "prescribe",
            "fdb_code": "12345",
            "sig": "Take 1 tab daily",
            "prescriber_id": "staff-1",
            "icd10_codes": ["K21.9"],
            "quantity_to_dispense": 30,
            "days_supply": 30,
            "refills": 0,
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.prescribe"


@patch("exam_chart_app.api.emitters.ReferCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_refer_raises(mock_rfv, mock_refer):
    mock_refer.return_value.originate.side_effect = ValueError("refer boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "refer",
            "service_provider": {"first_name": "Jane", "last_name": "Doe"},
            "notes_to_specialist": "please see",
            "diagnosis_codes": ["K21.9"],
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.refer"


@patch("exam_chart_app.api.emitters.GoalCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_goal_raises(mock_rfv, mock_goal):
    mock_goal.return_value.originate.side_effect = ValueError("goal boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "goal", "goal_statement": "lose 10 lbs",
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.goal"


@patch("exam_chart_app.api.emitters.PlanCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_plan_item_raises(mock_rfv, mock_plan):
    mock_plan.return_value.originate.side_effect = ValueError("plan boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "plan_item", "narrative": "Increase exercise",
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.plan_item"


@patch("exam_chart_app.api.emitters.FollowUpCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_follow_up_raises(mock_rfv, mock_followup):
    mock_followup.return_value.originate.side_effect = ValueError("fu boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [], "orders": [{
            "type": "follow_up", "requested_date": "2026-06-01",
        }]},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.orders.follow_up"


@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_500_when_diagnose_raises(mock_rfv, mock_dx):
    mock_dx.return_value.originate.side_effect = ValueError("dx boom")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [{"code": "K21.9"}], "orders": []},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["section"] == "ap.diagnoses"


@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_lets_unexpected_exceptions_propagate(mock_rfv, mock_dx):
    """Per-emitter catches were narrowed from `except Exception` to
    `(ValueError, TypeError)` so that genuine programming bugs surface
    in Sentry instead of being masked as a generic 500. KeyError,
    AttributeError, RuntimeError, etc. should propagate."""
    import pytest
    mock_dx.return_value.originate.side_effect = RuntimeError("not a validation failure")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [{"code": "K21.9"}], "orders": []},
    }
    with pytest.raises(RuntimeError):
        _make_api(json_body=payload).finalize()


@patch("exam_chart_app.api.emitters.AssessCommand")
@patch("exam_chart_app.api.emitters.DiagnoseCommand")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_400_when_assess_status_unknown(mock_rfv, mock_dx, mock_assess):
    mock_dx.return_value.originate.return_value = "DX"
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "x"},
        "ap": {"diagnoses": [{
            "code": "K21.9",
            "assessment": {"status": "made-up-status", "narrative": "x"},
        }], "orders": []},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content.decode())
    assert body["errors"][0]["field"] == "assessment.status"


# ----- get_patient_conditions: no ICD coding found → skipped -----


@patch("exam_chart_app.api.exam_api.Condition")
def test_get_patient_conditions_skips_conditions_without_icd(mock_cond_cls):
    """A condition whose codings are all non-ICD and non-shape-matching
    is filtered out of the response."""
    weird_coding = MagicMock(code="abc", system="http://example.com/other")
    weird_coding.display = "Weird"
    cond = MagicMock(id="cond-3", clinical_status="active")
    cond.codings.all.return_value = [weird_coding]
    qs = MagicMock()
    qs.prefetch_related.return_value.__getitem__.return_value = [cond]
    mock_cond_cls.objects.filter.return_value = qs

    api_obj = _make_api(query={"patient_id": "22222222-2222-2222-2222-222222222222"})
    responses = api_obj.get_patient_conditions()
    body = json.loads(responses[0].content.decode())
    assert body["conditions"] == []


# ----- mark_finalized: narrow catch swallows DB errors, propagates others -----


@patch("exam_chart_app.api.exam_api.mark_finalized")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_swallows_mark_finalized_db_error(mock_rfv, mock_mark):
    """A transient DB error from mark_finalized must not turn a successful
    finalize into a 500. The originate effects have already been built;
    swallowing keeps the user's commands flowing while log.exception
    pages on-call."""
    from django.db import OperationalError
    mock_rfv.return_value.originate.return_value = "RFV"
    mock_mark.side_effect = OperationalError("server closed the connection")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
    }
    responses = _make_api(json_body=payload).finalize()
    assert responses[0].status_code == HTTPStatus.OK
    body = json.loads(responses[0].content.decode())
    assert body["success"] is True


@patch("exam_chart_app.api.exam_api.mark_finalized")
@patch("exam_chart_app.api.exam_api.ReasonForVisitCommand")
def test_finalize_propagates_mark_finalized_programming_bug(mock_rfv, mock_mark):
    """Locks the narrowed-catch invariant: AttributeError / KeyError /
    TypeError from a renamed AttributeHub method or sandbox attribute
    block must NOT be swallowed. Those need to reach Sentry as 500s."""
    import pytest
    mock_rfv.return_value.originate.return_value = "RFV"
    mock_mark.side_effect = AttributeError("AttributeHub.set_attribute renamed")
    payload = {
        "note_uuid": "11111111-1111-1111-1111-111111111111",
        "rfv": {"comment": "Annual visit"},
    }
    with pytest.raises(AttributeError):
        _make_api(json_body=payload).finalize()
