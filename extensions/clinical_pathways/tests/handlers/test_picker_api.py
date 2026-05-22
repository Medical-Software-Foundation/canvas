"""Tests for clinical_pathways.handlers.picker_api."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from clinical_pathways.handlers import picker_api as picker_mod
from clinical_pathways.handlers.picker_api import PickerAPI, _parse_int
from clinical_pathways.models import Pathway, PathwayRun


def _make_handler() -> PickerAPI:
    handler = PickerAPI()
    handler.request = MagicMock()
    handler.request.query_params = {}
    handler.request.json.return_value = {}
    return handler


class TestParseInt:
    def test_parses_int_string(self) -> None:
        assert _parse_int("42") == 42

    def test_returns_none_for_none(self) -> None:
        assert _parse_int(None) is None

    def test_returns_none_for_garbage(self) -> None:
        assert _parse_int("not-an-int") is None
        assert _parse_int([]) is None


class TestStaticAssetRoutes:
    def test_index_returns_html_response(self) -> None:
        handler = _make_handler()
        responses = handler.index()
        assert len(responses) == 1
        resp = responses[0]
        assert resp.status_code == HTTPStatus.OK
        assert resp.content_type == "text/html"

    def test_main_js_returns_javascript_response(self) -> None:
        handler = _make_handler()
        responses = handler.main_js()
        resp = responses[0]
        assert resp.content_type == "application/javascript"
        assert resp.status_code == HTTPStatus.OK
        assert resp.headers["Cache-Control"] == "no-cache"

    def test_styles_css_returns_css_response(self) -> None:
        handler = _make_handler()
        responses = handler.styles_css()
        resp = responses[0]
        assert resp.content_type == "text/css"
        assert resp.status_code == HTTPStatus.OK
        assert resp.headers["Cache-Control"] == "no-cache"


class TestSearchPathways:
    def test_returns_published_active_pathways_ordered_by_title(self) -> None:
        handler = _make_handler()
        handler.request.query_params = {}

        pw1 = MagicMock(dbid=1, title="Asthma", description="A")
        pw2 = MagicMock(dbid=2, title="Bronchitis", description="B")

        qs = MagicMock()
        qs.order_by.return_value.__getitem__.return_value = [pw1, pw2]

        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.search_pathways()

        assert responses[0].data == {
            "pathways": [
                {"dbid": 1, "title": "Asthma", "description": "A"},
                {"dbid": 2, "title": "Bronchitis", "description": "B"},
            ]
        }
        mock_objects.filter.assert_called_once_with(is_active=True, status="published")

    def test_applies_title_filter_when_query_provided(self) -> None:
        handler = _make_handler()
        handler.request.query_params = {"q": "asthma"}

        qs = MagicMock()
        narrowed = MagicMock()
        qs.filter.return_value = narrowed
        narrowed.order_by.return_value.__getitem__.return_value = []

        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            handler.search_pathways()

        qs.filter.assert_called_once_with(title__icontains="asthma")


class TestStartPathway:
    def _pathway_with_definition(self, definition: dict, dbid: int = 11) -> MagicMock:
        pw = MagicMock(spec=Pathway)
        pw.dbid = dbid
        pw.title = "Asthma"
        pw.definition = definition
        return pw

    def test_rejects_missing_note_uuid(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {"pathway_dbid": 1}
        responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "note_uuid" in responses[0].data["error"]

    def test_rejects_missing_pathway_dbid(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {"note_uuid": "note-1"}
        responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "pathway_dbid" in responses[0].data["error"]

    def test_rejects_when_pathway_not_found(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {
            "note_uuid": "note-1",
            "pathway_dbid": 99,
        }
        qs = MagicMock()
        qs.first.return_value = None
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.NOT_FOUND

    def test_rejects_old_definition_version(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {
            "note_uuid": "note-1",
            "pathway_dbid": 5,
        }
        pw = self._pathway_with_definition({"version": 2}, dbid=5)
        qs = MagicMock()
        qs.first.return_value = pw
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "older format" in responses[0].data["error"]

    def test_rejects_when_no_starting_step(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {
            "note_uuid": "note-1",
            "pathway_dbid": 5,
        }
        pw = self._pathway_with_definition(
            {"version": 3, "start_step_id": "s_missing", "steps": []},
        )
        qs = MagicMock()
        qs.first.return_value = pw
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST
        assert "no starting step" in responses[0].data["error"]

    def test_rejects_when_start_step_has_no_questionnaire(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {
            "note_uuid": "note-1",
            "pathway_dbid": 5,
        }
        pw = self._pathway_with_definition(
            {
                "version": 3,
                "start_step_id": "s_a",
                "steps": [{"step_id": "s_a"}],
            },
        )
        qs = MagicMock()
        qs.first.return_value = pw
        with patch.object(Pathway, "objects") as mock_objects:
            mock_objects.filter.return_value = qs
            responses = handler.start_pathway()
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST

    def test_starts_pathway_and_returns_run_payload(
        self, stub_effect_type: type
    ) -> None:
        handler = _make_handler()
        handler.request.json.return_value = {
            "note_uuid": "note-1",
            "pathway_dbid": 5,
        }
        pw = self._pathway_with_definition(
            {
                "version": 3,
                "start_step_id": "s_a",
                "steps": [
                    {"step_id": "s_a", "questionnaire_id": "qn-abc"},
                ],
            },
            dbid=5,
        )
        qs = MagicMock()
        qs.first.return_value = pw

        # Wire PathwayRun(...) to a MagicMock so we can capture .save() and .dbid.
        run_instance = MagicMock()
        run_instance.dbid = 77

        with (
            patch.object(Pathway, "objects") as mock_objects,
            patch.object(picker_mod, "PathwayRun", return_value=run_instance) as mock_run_cls,
        ):
            mock_objects.filter.return_value = qs
            responses = handler.start_pathway()

        # The handler emits a BatchOriginateCommandEffect plus a JSONResponse.
        assert len(responses) == 2
        effect, json_resp = responses
        assert isinstance(effect, stub_effect_type)
        assert effect.tag == "BatchOriginateCommandEffect"
        assert json_resp.status_code == HTTPStatus.OK
        assert json_resp.data == {
            "status": "started",
            "pathway_run_dbid": 77,
            "pathway_title": "Asthma",
        }

        # The PathwayRun constructor saw the right kwargs and was saved.
        kwargs = mock_run_cls.call_args.kwargs
        assert kwargs["note_uuid"] == "note-1"
        assert kwargs["pathway_id"] == 5
        assert kwargs["current_step_id"] == "s_a"
        assert kwargs["inserted_questionnaires"] == ["qn-abc"]
        assert kwargs["status"] == "active"
        run_instance.save.assert_called_once_with()

    def test_handles_empty_json_body(self) -> None:
        handler = _make_handler()
        handler.request.json.return_value = None
        responses = handler.start_pathway()
        # Missing note_uuid triggers the first guard.
        assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize(
    "definition",
    [
        # `steps` missing entirely
        {"version": 3, "start_step_id": "s_a"},
        # `steps` not a list of dicts
        {"version": 3, "start_step_id": "s_a", "steps": ["junk"]},
    ],
)
def test_start_pathway_handles_malformed_steps(definition: dict) -> None:
    handler = _make_handler()
    handler.request.json.return_value = {"note_uuid": "n", "pathway_dbid": 1}
    pw = MagicMock(dbid=1, title="X", definition=definition)
    qs = MagicMock()
    qs.first.return_value = pw
    with patch.object(Pathway, "objects") as mock_objects:
        mock_objects.filter.return_value = qs
        responses = handler.start_pathway()
    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
