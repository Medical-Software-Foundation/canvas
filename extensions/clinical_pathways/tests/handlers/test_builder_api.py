"""Tests for clinical_pathways.handlers.builder_api."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data.questionnaire import Questionnaire

from clinical_pathways.handlers import builder_api as builder_mod
from clinical_pathways.handlers.builder_api import (
    BuilderAPI,
    _empty_definition,
    _new_recommendation_id,
    _new_rule_id,
    _new_step_id,
    _now_iso,
    _parse_int,
    _serialize_pathway_full,
    _serialize_pathway_summary,
    _validate_pathway,
)
from clinical_pathways.models import Pathway


def _make_handler() -> BuilderAPI:
    handler = BuilderAPI()
    handler.request = MagicMock()
    handler.request.query_params = {}
    handler.request.path_params = {}
    handler.request.json.return_value = {}
    return handler


# ---------- Module-level helpers ----------


class TestModuleHelpers:
    def test_parse_int_valid(self) -> None:
        assert _parse_int("42") == 42

    def test_parse_int_none(self) -> None:
        assert _parse_int(None) is None

    def test_parse_int_garbage(self) -> None:
        assert _parse_int("xyz") is None
        assert _parse_int(object()) is None

    def test_now_iso_returns_string_with_t_separator(self) -> None:
        value = _now_iso()
        assert "T" in value and value.endswith("+00:00")

    def test_new_step_id_prefix(self) -> None:
        assert _new_step_id().startswith("s_")

    def test_new_rule_id_prefix(self) -> None:
        assert _new_rule_id().startswith("r_")

    def test_new_recommendation_id_prefix(self) -> None:
        assert _new_recommendation_id().startswith("rec_")

    def test_empty_definition_shape(self) -> None:
        d = _empty_definition()
        assert d == {
            "version": 3,
            "start_step_id": None,
            "loaded_questionnaires": [],
            "steps": [],
            "recommendations": [],
        }


class TestSerialize:
    def test_serialize_summary_extracts_top_level_fields(self) -> None:
        pw = MagicMock(dbid=3, title="T", description="D", status="draft")
        pw.updated_at = MagicMock()
        pw.updated_at.isoformat.return_value = "2026-01-01T00:00:00+00:00"
        summary = _serialize_pathway_summary(pw)
        assert summary == {
            "dbid": 3,
            "title": "T",
            "description": "D",
            "status": "draft",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def test_serialize_summary_handles_missing_updated_at(self) -> None:
        pw = MagicMock(dbid=3, title="T", description="D", status="draft")
        pw.updated_at = None
        summary = _serialize_pathway_summary(pw)
        assert summary["updated_at"] is None

    def test_serialize_full_falls_back_to_empty_definition(self) -> None:
        pw = MagicMock(dbid=1, title="T", description="", status="draft")
        pw.updated_at = None
        pw.definition = None
        full = _serialize_pathway_full(pw)
        assert full["definition"] == _empty_definition()

    def test_serialize_full_passes_through_definition(self) -> None:
        pw = MagicMock(dbid=1, title="T", description="", status="draft")
        pw.updated_at = None
        pw.definition = {"version": 3, "steps": [{"step_id": "x"}]}
        full = _serialize_pathway_full(pw)
        assert full["definition"]["steps"] == [{"step_id": "x"}]


# ---------- _validate_pathway ----------


def _questionnaire_exists(_ids: set[str]) -> None:
    """Patch Questionnaire.objects.filter(id=...).exists() to return True/False."""


class TestValidatePathway:
    def test_non_dict_definition_errors(self) -> None:
        issues = _validate_pathway("not a dict")  # type: ignore[arg-type]
        assert issues[0]["severity"] == "error"
        assert "no definition" in issues[0]["message"]

    def test_old_version_errors(self) -> None:
        issues = _validate_pathway({"version": 2})
        assert issues[0]["severity"] == "error"
        assert "older format" in issues[0]["message"]

    def test_no_steps_errors(self) -> None:
        issues = _validate_pathway(
            {"version": 3, "start_step_id": None, "steps": [], "recommendations": []}
        )
        assert any("Add at least one step" in i["message"] for i in issues)

    def test_missing_start_step_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": None,
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("Pick which step" in i["message"] for i in issues)

    def test_step_missing_questionnaire_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {"step_id": "s_a", "question_id": "q1", "rules": [], "otherwise": None},
                    ],
                    "recommendations": [],
                }
            )
        assert any("questionnaire reference" in i["message"] for i in issues)

    def test_step_with_stale_questionnaire_emits_warning(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = False
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn-stale",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any(
            i["severity"] == "warning" and "no longer available" in i["message"]
            for i in issues
        )

    def test_step_with_no_rules_and_no_otherwise_warns(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any(
            "no rules and no Otherwise" in i["message"] for i in issues
        )

    def test_step_missing_question_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "rules": [],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("question reference" in i["message"] for i in issues)

    def test_rule_target_unknown_step_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [{"question_id": "q1", "operator": "eq"}],
                                    "then": {"type": "step", "target_id": "s_nonexistent"},
                                }
                            ],
                            "otherwise": None,
                        },
                    ],
                    "recommendations": [],
                }
            )
        assert any(
            i["severity"] == "error" and "step that's not in this pathway" in i["message"]
            for i in issues
        )

    def test_rule_target_unknown_recommendation_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [{"question_id": "q1", "operator": "eq"}],
                                    "then": {"type": "recommendation", "target_id": "rec_x"},
                                }
                            ],
                            "otherwise": None,
                        },
                    ],
                    "recommendations": [],
                }
            )
        assert any("recommendation that's not in this pathway" in i["message"] for i in issues)

    def test_rule_target_unknown_type_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [{"question_id": "q1", "operator": "eq"}],
                                    "then": {"type": "bogus", "target_id": "x"},
                                }
                            ],
                            "otherwise": None,
                        },
                    ],
                    "recommendations": [],
                }
            )
        assert any("unknown type" in i["message"] for i in issues)

    def test_rule_missing_then_target_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [{"question_id": "q1", "operator": "eq"}],
                                    "then": None,
                                }
                            ],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("Routing target is missing" in i["message"] for i in issues)

    def test_rule_with_empty_conditions_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [],
                                    "then": {"type": "step", "target_id": "s_a"},
                                }
                            ],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("Rule has no conditions" in i["message"] for i in issues)

    def test_bad_connector_value_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [
                                        {"question_id": "q1", "operator": "eq"},
                                        {
                                            "question_id": "q1",
                                            "operator": "eq",
                                            "connector": "XOR",
                                        },
                                    ],
                                    "then": {"type": "step", "target_id": "s_a"},
                                }
                            ],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("connector must be 'and' or 'or'" in i["message"] for i in issues)

    def test_malformed_step_entry_errors(self) -> None:
        issues = _validate_pathway(
            {
                "version": 3,
                "start_step_id": None,
                "steps": ["not-a-dict"],
                "recommendations": [],
            }
        )
        assert any("Malformed step entry" in i["message"] for i in issues)

    def test_malformed_rule_entry_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": ["junk-rule"],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": [],
                }
            )
        assert any("Malformed rule entry" in i["message"] for i in issues)

    def test_unknown_recommendation_command_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": {"type": "recommendation", "target_id": "rec1"},
                        }
                    ],
                    "recommendations": [
                        {
                            "recommendation_id": "rec1",
                            "command_key": "unknown_cmd",
                            "params": {},
                        }
                    ],
                }
            )
        assert any("Unknown recommendation command" in i["message"] for i in issues)

    def test_recommendation_missing_command_key_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": {"type": "recommendation", "target_id": "rec1"},
                        }
                    ],
                    "recommendations": [
                        {"recommendation_id": "rec1", "params": {}},
                    ],
                }
            )
        assert any("missing a command type" in i["message"] for i in issues)

    def test_recommendation_missing_required_field_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": {"type": "recommendation", "target_id": "rec1"},
                        }
                    ],
                    "recommendations": [
                        {
                            "recommendation_id": "rec1",
                            "name": "Mild",
                            "command_key": "pathway_classification",
                            "params": {"title": "", "body": ""},
                        }
                    ],
                }
            )
        # Two required fields missing → at least two errors mentioning required field.
        msgs = [i["message"] for i in issues if "missing required field" in i["message"]]
        assert len(msgs) >= 2

    def test_malformed_recommendation_entry_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [],
                            "otherwise": None,
                        }
                    ],
                    "recommendations": ["not-a-dict"],
                }
            )
        assert any("Malformed recommendation entry" in i["message"] for i in issues)

    def test_valid_pathway_produces_no_errors(self) -> None:
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.exists.return_value = True
            issues = _validate_pathway(
                {
                    "version": 3,
                    "start_step_id": "s_a",
                    "steps": [
                        {
                            "step_id": "s_a",
                            "questionnaire_id": "qn",
                            "question_id": "q1",
                            "rules": [
                                {
                                    "rule_id": "r1",
                                    "conditions": [
                                        {"question_id": "q1", "operator": "eq"},
                                        {
                                            "question_id": "q1",
                                            "operator": "eq",
                                            "connector": "and",
                                        },
                                    ],
                                    "then": {"type": "recommendation", "target_id": "rec1"},
                                }
                            ],
                            "otherwise": {"type": "recommendation", "target_id": "rec1"},
                        }
                    ],
                    "recommendations": [
                        {
                            "recommendation_id": "rec1",
                            "name": "Mild",
                            "command_key": "pathway_classification",
                            "params": {"title": "T", "body": "B"},
                        }
                    ],
                }
            )
        errors = [i for i in issues if i["severity"] == "error"]
        assert errors == []


# ---------- Static asset routes ----------


class TestStaticAssetRoutes:
    def test_index_returns_html_response(self) -> None:
        handler = _make_handler()
        responses = handler.index()
        assert responses[0].content_type == "text/html"

    def test_main_js_returns_javascript(self) -> None:
        handler = _make_handler()
        responses = handler.main_js()
        assert responses[0].content_type == "application/javascript"

    def test_styles_css_returns_css(self) -> None:
        handler = _make_handler()
        responses = handler.styles_css()
        assert responses[0].content_type == "text/css"


# ---------- Pathway CRUD ----------


class TestListPathways:
    def test_returns_active_pathways_serialized(self) -> None:
        handler = _make_handler()
        pw = MagicMock(dbid=1, title="A", description="", status="draft")
        pw.updated_at = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = [pw]
            responses = handler.list_pathways()
        assert responses[0].data == {
            "pathways": [
                {
                    "dbid": 1,
                    "title": "A",
                    "description": "",
                    "status": "draft",
                    "updated_at": None,
                }
            ]
        }
        mock_objects.filter.assert_called_once_with(is_active=True)


class TestCreatePathway:
    def test_creates_pathway_with_title_from_body(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {"title": "  Asthma  ", "description": "x"}

        created = MagicMock()
        created.dbid = 7
        created.title = "Asthma"
        created.description = "x"
        created.status = "draft"
        created.updated_at = None
        created.definition = _empty_definition()

        with patch.object(builder_mod, "Pathway", return_value=created) as mock_cls:
            responses = handler.create_pathway()

        assert responses[0].status_code == HTTPStatus.CREATED
        created.save.assert_called_once_with()
        # The constructor was called with stripped title.
        assert mock_cls.call_args.kwargs["title"] == "Asthma"
        assert mock_cls.call_args.kwargs["status"] == "draft"

    def test_creates_pathway_with_fallback_title_when_blank(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {"title": "   "}
        created = MagicMock(
            dbid=1, title="Untitled pathway", description="", status="draft",
        )
        created.updated_at = None
        created.definition = None
        with patch.object(builder_mod, "Pathway", return_value=created) as mock_cls:
            handler.create_pathway()
        assert mock_cls.call_args.kwargs["title"] == "Untitled pathway"

    def test_creates_pathway_with_empty_body(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = None
        created = MagicMock(
            dbid=1, title="Untitled pathway", description="", status="draft",
        )
        created.updated_at = None
        created.definition = None
        with patch.object(builder_mod, "Pathway", return_value=created):
            responses = handler.create_pathway()
        assert responses[0].status_code == HTTPStatus.CREATED


class TestGetPathway:
    def test_returns_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.get_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_full_pathway(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        pw = MagicMock(
            dbid=9, title="T", description="", status="published",
        )
        pw.updated_at = None
        pw.definition = {"version": 3, "steps": []}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.get_pathway()
        assert responses[0].data["definition"]["version"] == 3


class TestReplacePathway:
    def test_returns_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.replace_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_updates_title_description_and_definition(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        handler.request.json.return_value = {
            "title": "New title",
            "description": "New desc",
            "definition": {"version": 3, "steps": []},
        }
        pw = MagicMock(dbid=9, title="Old", description="", status="draft")
        pw.updated_at = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.replace_pathway()
        assert pw.title == "New title"
        assert pw.description == "New desc"
        assert pw.definition == {"version": 3, "steps": []}
        pw.save.assert_called_once_with()
        assert responses[0].status_code == HTTPStatus.OK

    def test_blank_title_falls_back_to_existing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        handler.request.json.return_value = {"title": "   "}
        pw = MagicMock(dbid=9, title="Old", description="", status="draft")
        pw.updated_at = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            handler.replace_pathway()
        # Blank input does not overwrite the existing title.
        assert pw.title == "Old"

    def test_non_dict_definition_returns_400(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        handler.request.json.return_value = {"definition": "not a dict"}
        pw = MagicMock(dbid=9, title="Old", description="", status="draft")
        pw.updated_at = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.replace_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_empty_body_only_saves(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        handler.request.json.return_value = None
        pw = MagicMock(dbid=9, title="Old", description="", status="draft")
        pw.updated_at = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.replace_pathway()
        pw.save.assert_called_once_with()
        assert responses[0].status_code == HTTPStatus.OK


class TestDeletePathway:
    def test_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.delete_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_soft_deletes_and_demotes_status(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        pw = MagicMock(dbid=9, is_active=True, status="published")
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.delete_pathway()
        assert pw.is_active is False
        assert pw.status == "draft"
        pw.save.assert_called_once_with()
        assert responses[0].data == {"deleted": True}


class TestPublishPathway:
    def test_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.publish_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_400_when_validation_errors(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        pw = MagicMock(dbid=9, status="draft")
        pw.definition = {"version": 2}  # triggers validator error
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.publish_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert responses[0].data["published"] is False

    def test_publishes_when_valid(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        valid_def = {
            "version": 3,
            "start_step_id": "s_a",
            "steps": [
                {
                    "step_id": "s_a",
                    "questionnaire_id": "qn",
                    "question_id": "q1",
                    "rules": [],
                    "otherwise": {"type": "recommendation", "target_id": "rec1"},
                }
            ],
            "recommendations": [
                {
                    "recommendation_id": "rec1",
                    "name": "X",
                    "command_key": "pathway_classification",
                    "params": {"title": "T", "body": "B"},
                }
            ],
        }
        pw = MagicMock(dbid=9, status="draft")
        pw.definition = valid_def
        with (
            patch.object(Pathway, "objects") as mock_objects,
            patch.object(Questionnaire, "objects") as mock_qn,
        ):
            mock_objects.filter.return_value.first.return_value = pw
            mock_qn.filter.return_value.exists.return_value = True
            responses = handler.publish_pathway()
        assert pw.status == "published"
        pw.save.assert_called_once_with()
        assert responses[0].data["published"] is True


class TestUnpublishPathway:
    def test_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.unpublish_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_demotes_to_draft(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        pw = MagicMock(dbid=9, status="published")
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.unpublish_pathway()
        assert pw.status == "draft"
        pw.save.assert_called_once_with()
        assert responses[0].data == {"unpublished": True}


class TestValidatePathwayRoute:
    def test_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.validate_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_returns_issues_list(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"pathway_dbid": "9"}
        pw = MagicMock(dbid=9)
        pw.definition = {"version": 2}  # any old version produces an error
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = pw
            responses = handler.validate_pathway()
        assert "issues" in responses[0].data
        assert responses[0].data["issues"][0]["severity"] == "error"


class TestQuestionnaireCatalog:
    def test_list_questionnaires_serializes_minimal_fields(self) -> None:
        handler = _make_handler()
        handler.request.query_params = {}
        item = MagicMock(name="qn-item")
        item.id = "qn-id-1"
        item.name = "Asthma triage"
        item.code = "AST"
        qs = MagicMock()
        qs.order_by.return_value.__getitem__.return_value = [item]
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.list_questionnaires()
        assert responses[0].data == {
            "questionnaires": [
                {"id": "qn-id-1", "name": "Asthma triage", "code": "AST"},
            ]
        }
        mock_objects.filter.assert_called_once_with(
            status="AC", can_originate_in_charting=True
        )

    def test_list_questionnaires_filters_by_name_when_query_provided(self) -> None:
        handler = _make_handler()
        handler.request.query_params = {"q": "asthma"}
        qs = MagicMock()
        narrowed = MagicMock()
        qs.filter.return_value = narrowed
        narrowed.order_by.return_value.__getitem__.return_value = []
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            handler.list_questionnaires()
        qs.filter.assert_called_once_with(name__icontains="asthma")

    def test_get_questionnaire_detail_404_when_missing(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"questionnaire_id": "qn-1"}
        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = None
            responses = handler.get_questionnaire_detail()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_get_questionnaire_detail_returns_questions_and_options(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"questionnaire_id": "qn-1"}

        option = MagicMock()
        option.dbid = 99
        option.value = "yes"
        option.name = "Yes"

        opt_set = MagicMock()
        opt_set.type = "single-select"
        opt_set.name = "yes/no"
        opt_set.options.all.return_value = [option]

        question = MagicMock()
        question.id = "q-uuid-1"
        question.name = "Has cough?"
        question.code = "COUGH"
        question.response_option_set = opt_set

        questionnaire = MagicMock()
        questionnaire.id = "qn-uuid-1"
        questionnaire.name = "Asthma"
        questionnaire.code = "AST"
        questionnaire.questions.all.return_value = [question]

        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = questionnaire
            responses = handler.get_questionnaire_detail()

        data = responses[0].data
        assert data["id"] == "qn-uuid-1"
        assert data["questions"][0]["options"][0] == {
            "id": "99",
            "value": "yes",
            "name": "Yes",
        }

    def test_get_questionnaire_detail_handles_question_with_no_option_set(self) -> None:
        handler = _make_handler()
        handler.request.path_params = {"questionnaire_id": "qn-1"}

        question = MagicMock()
        question.id = "q-uuid-2"
        question.name = "Free text"
        question.code = "FT"
        question.response_option_set = None

        questionnaire = MagicMock()
        questionnaire.id = "qn-uuid-1"
        questionnaire.name = "X"
        questionnaire.code = "X"
        questionnaire.questions.all.return_value = [question]

        with patch.object(Questionnaire, "objects") as mock_objects:
            mock_objects.filter.return_value.first.return_value = questionnaire
            responses = handler.get_questionnaire_detail()

        q0 = responses[0].data["questions"][0]
        assert q0["options"] == []
        assert q0["response_set_type"] is None
        assert q0["response_set_name"] is None


class TestTerminalCommandCatalogRoute:
    def test_returns_catalog_payload(self) -> None:
        handler = _make_handler()
        responses = handler.list_terminal_commands()
        assert "terminal_commands" in responses[0].data
        keys = [tc["key"] for tc in responses[0].data["terminal_commands"]]
        assert "pathway_classification" in keys


@pytest.mark.parametrize(
    "version", [1, 2],
)
def test_validate_pathway_rejects_old_versions(version: int) -> None:
    issues = _validate_pathway({"version": version})
    assert any("older format" in i["message"] for i in issues)
