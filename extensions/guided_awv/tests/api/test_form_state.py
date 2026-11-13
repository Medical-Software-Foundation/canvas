"""Tests for form state persistence (cache + legacy fallback)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from guided_awv.api.awv_api import (
    GetFormStateHandler,
    SaveAdvanceCarePlanningHandler,
    SaveAlcoholScreeningHandler,
    SaveCognitiveAssessmentHandler,
    SaveCurrentProvidersHandler,
    SaveDepressionScreeningHandler,
    SaveFallRiskHandler,
    SaveFamilyHistoryHandler,
    SaveFunctionalAbilityHandler,
    SaveHRAHandler,
    SaveHearingVisionHandler,
    SavePlanHandler,
    SavePreventiveServicesHandler,
    SaveVitalsHandler,
    ScheduleFollowupHandler,
    _FORM_STATE_TAG,
    _extract_form_states,
)


def _make_tag(section_id: str, fields: dict) -> str:
    return f"[//]: # ({_FORM_STATE_TAG}::{section_id}::{json.dumps(fields)})"


# ---- _extract_form_states (legacy reader, still used as GetFormStateHandler fallback) ----


class TestExtractFormStates:
    """Unit tests for _extract_form_states()."""

    def test_extracts_single_section(self) -> None:
        tag = _make_tag("depression", {"q1": 2})
        result = _extract_form_states([f"Clinical text\n{tag}"])
        assert result == {"depression": {"q1": 2}}

    def test_extracts_multiple_sections_from_multiple_narratives(self) -> None:
        tag1 = _make_tag("depression", {"q1": 2})
        tag2 = _make_tag("vitals", {"bp": 120})
        result = _extract_form_states([f"text\n{tag1}", f"text\n{tag2}"])
        assert result == {"depression": {"q1": 2}, "vitals": {"bp": 120}}

    def test_last_write_wins_for_same_section(self) -> None:
        tag1 = _make_tag("depression", {"q1": 1})
        tag2 = _make_tag("depression", {"q1": 3})
        result = _extract_form_states([f"text\n{tag1}", f"text\n{tag2}"])
        assert result == {"depression": {"q1": 3}}

    def test_skips_malformed_json(self) -> None:
        tag = f"[//]: # ({_FORM_STATE_TAG}::depression::not-valid-json)"
        result = _extract_form_states([f"text\n{tag}"])
        assert result == {}

    def test_no_tags_returns_empty_dict(self) -> None:
        result = _extract_form_states(["Just clinical text", "More text"])
        assert result == {}

    def test_mixed_clinical_and_tag_content(self) -> None:
        tag = _make_tag("vitals", {"bp": 120})
        narrative = f"**Depression Screening**\nPHQ-2: 2/6\n{tag}"
        result = _extract_form_states([narrative])
        assert result == {"vitals": {"bp": 120}}


# ---- GetFormStateHandler ----


class TestGetFormStateHandler:
    """Tests for the GET /awv/form-state endpoint."""

    def test_missing_note_id_returns_400(self) -> None:
        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = None

        with patch("guided_awv.api.awv_api.JSONResponse") as mock_json:
            mock_json.return_value = "error"
            handler.get()
            assert mock_json.call_args[1]["status_code"] == 400

    @patch("guided_awv.api.awv_api._get_all_form_states")
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_returns_cached_sections_when_available(
        self, mock_json: MagicMock, mock_get_all: MagicMock
    ) -> None:
        """Cache hit returns sections directly without scanning commands."""
        mock_get_all.return_value = {"vitals": {"bp": 120}, "hra": {"q1": "Good"}}
        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"] == {"vitals": {"bp": 120}, "hra": {"q1": "Good"}}

    @patch("canvas_sdk.v1.data.command.Command")
    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_falls_back_to_command_scan_on_cache_miss(
        self, mock_json: MagicMock, mock_get_all: MagicMock, mock_cmd_cls: MagicMock
    ) -> None:
        """Cache miss triggers legacy command scanning fallback."""
        tag = _make_tag("depression", {"q1": 2})
        cmd = MagicMock()
        cmd.data = {"narrative": f"text\n{tag}"}
        mock_cmd_cls.objects.filter.return_value.order_by.return_value = [cmd]

        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"] == {"depression": {"q1": 2}}

    @patch("canvas_sdk.v1.data.command.Command")
    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_no_commands_returns_empty_sections(
        self, mock_json: MagicMock, mock_get_all: MagicMock, mock_cmd_cls: MagicMock
    ) -> None:
        mock_cmd_cls.objects.filter.return_value.order_by.return_value = []
        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"] == {}

    @patch("canvas_sdk.v1.data.command.Command")
    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_parses_cmd_data_as_json_string(
        self, mock_json: MagicMock, mock_get_all: MagicMock, mock_cmd_cls: MagicMock
    ) -> None:
        tag = _make_tag("vitals", {"bp": 120})
        cmd = MagicMock()
        cmd.data = json.dumps({"narrative": f"text\n{tag}"})
        mock_cmd_cls.objects.filter.return_value.order_by.return_value = [cmd]

        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"] == {"vitals": {"bp": 120}}

    @patch("canvas_sdk.v1.data.command.Command")
    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_handles_plain_string_data(
        self, mock_json: MagicMock, mock_get_all: MagicMock, mock_cmd_cls: MagicMock
    ) -> None:
        """cmd.data is a non-JSON string — falls through to raw append."""
        tag = _make_tag("plan", {"notes": "ok"})
        cmd = MagicMock()
        cmd.data = f"plain narrative\n{tag}"
        mock_cmd_cls.objects.filter.return_value.order_by.return_value = [cmd]

        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"] == {"plan": {"notes": "ok"}}

    @patch("canvas_sdk.v1.data.command.Command")
    @patch("guided_awv.api.awv_api._get_all_form_states", return_value={})
    @patch("guided_awv.api.awv_api.JSONResponse")
    def test_multiple_commands_last_write_wins(
        self, mock_json: MagicMock, mock_get_all: MagicMock, mock_cmd_cls: MagicMock
    ) -> None:
        tag1 = _make_tag("depression", {"q1": 1})
        tag2 = _make_tag("depression", {"q1": 3})
        cmd1 = MagicMock()
        cmd1.data = {"narrative": f"text\n{tag1}"}
        cmd2 = MagicMock()
        cmd2.data = {"narrative": f"text\n{tag2}"}
        mock_cmd_cls.objects.filter.return_value.order_by.return_value = [cmd1, cmd2]

        handler = GetFormStateHandler(MagicMock())
        handler.request = MagicMock()
        handler.request.query_params.get.return_value = "note-1"
        mock_json.return_value = "ok"

        handler.get()

        assert mock_json.call_args[0][0]["sections"]["depression"] == {"q1": 3}


# ---- Form state caching across all POST handlers ----

# (HandlerClass, section_id, minimal_body that passes validation)
_HANDLER_CASES = [
    (SaveVitalsHandler, "vitals", {"note_id": "n1"}),
    (SaveDepressionScreeningHandler, "depressionscreening", {"note_id": "n1"}),
    (SaveCognitiveAssessmentHandler, "cognitiveassessment", {"note_id": "n1"}),
    (SaveFallRiskHandler, "fallrisk", {"note_id": "n1"}),
    (SavePlanHandler, "assessmentplan", {"note_id": "n1"}),
    (ScheduleFollowupHandler, "followupscheduling", {"note_id": "n1"}),
    (SaveHRAHandler, "hra", {"note_id": "n1"}),
    (SaveFamilyHistoryHandler, "familyhistory", {"note_id": "n1", "relatives": {"Mother": {"status": "Living", "age": "65", "conditions": []}}}),
    (SaveFunctionalAbilityHandler, "functionalability", {"note_id": "n1"}),
    (SaveAdvanceCarePlanningHandler, "advancecareplanning", {"note_id": "n1"}),
    (SavePreventiveServicesHandler, "preventiveservices", {"note_id": "n1", "services": {"flu": "ordered"}}),
    (SaveCurrentProvidersHandler, "currentproviders", {"note_id": "n1"}),
    (SaveHearingVisionHandler, "hearingvision", {"note_id": "n1"}),
    (SaveAlcoholScreeningHandler, "alcoholscreening", {"note_id": "n1"}),
]


class TestFormStateCaching:
    """Verify each POST handler pops _form_fields and saves to cache."""

    @pytest.mark.parametrize(
        "handler_cls,section_id,body",
        _HANDLER_CASES,
        ids=[c[0].__name__ for c in _HANDLER_CASES],
    )
    def test_saves_form_state_to_cache(
        self, handler_cls: type, section_id: str, body: dict[str, object], _mock_form_state_cache: MagicMock
    ) -> None:
        form_fields = {"field1": "val1"}
        request_body = {**body, "_form_fields": form_fields}

        with (
            patch("guided_awv.api.awv_api.PlanCommand") as mock_plan,
            patch("guided_awv.api.awv_api.JSONResponse") as mock_json,
            patch("guided_awv.api.awv_api.VitalsCommand"),
            patch("guided_awv.api.awv_api.FollowUpCommand"),
            patch("guided_awv.api.awv_api.StructuredAssessmentCommand"),
            patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid"),
            patch("guided_awv.api.awv_api.FamilyHistoryCommand"),
            patch("guided_awv.api.awv_api.Coding"),
            patch("guided_awv.api.awv_api.ChartSectionReviewCommand"),
            patch("guided_awv.api.awv_api.TaskCommand"),
            patch("guided_awv.api.awv_api.ImagingOrderCommand"),
            patch("guided_awv.api.awv_api.PerformCommand"),
            patch("guided_awv.api.awv_api.AddBillingLineItem"),
            patch("guided_awv.api.awv_api.InstructCommand"),
            patch("guided_awv.api.awv_api.LabOrderCommand"),
            patch("guided_awv.api.awv_api.PrescribeCommand"),
        ):
            mock_cmd = MagicMock()
            mock_cmd.originate.return_value = "effect"
            mock_plan.return_value = mock_cmd
            mock_json.return_value = "json_ok"

            handler = handler_cls(MagicMock())
            handler.request = MagicMock()
            handler.request.json.return_value = request_body

            handler.post()

            # Verify _save_form_state was called with the correct args
            _mock_form_state_cache.assert_called_with("n1", section_id, form_fields)

    @pytest.mark.parametrize(
        "handler_cls,section_id,body",
        _HANDLER_CASES,
        ids=[c[0].__name__ for c in _HANDLER_CASES],
    )
    def test_form_fields_popped_from_body(self, handler_cls: type, section_id: str, body: dict[str, object]) -> None:
        request_body = {**body, "_form_fields": {"field1": "val1"}}

        with (
            patch("guided_awv.api.awv_api.PlanCommand") as mock_plan,
            patch("guided_awv.api.awv_api.JSONResponse") as mock_json,
            patch("guided_awv.api.awv_api.VitalsCommand"),
            patch("guided_awv.api.awv_api.FollowUpCommand"),
            patch("guided_awv.api.awv_api.StructuredAssessmentCommand"),
            patch("guided_awv.api.awv_api._get_questionnaire_id", return_value="mock-qid"),
            patch("guided_awv.api.awv_api.FamilyHistoryCommand"),
            patch("guided_awv.api.awv_api.Coding"),
            patch("guided_awv.api.awv_api.ChartSectionReviewCommand"),
            patch("guided_awv.api.awv_api.TaskCommand"),
            patch("guided_awv.api.awv_api.ImagingOrderCommand"),
            patch("guided_awv.api.awv_api.PerformCommand"),
            patch("guided_awv.api.awv_api.AddBillingLineItem"),
            patch("guided_awv.api.awv_api.InstructCommand"),
            patch("guided_awv.api.awv_api.LabOrderCommand"),
            patch("guided_awv.api.awv_api.PrescribeCommand"),
        ):
            mock_cmd = MagicMock()
            mock_cmd.originate.return_value = "effect"
            mock_plan.return_value = mock_cmd
            mock_json.return_value = "json_ok"

            handler = handler_cls(MagicMock())
            handler.request = MagicMock()
            handler.request.json.return_value = request_body

            handler.post()

            assert "_form_fields" not in request_body
