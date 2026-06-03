from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_app(patient_id: str = "patient-uuid", secrets: dict[str, str] | None = None) -> Any:
    from chart_command_search.handlers.application import ChartSearchApp

    app = ChartSearchApp.__new__(ChartSearchApp)
    event = MagicMock()
    event.context = {"patient": {"id": patient_id}} if patient_id else {}
    app.event = event
    app.secrets = secrets or {}
    return app


@patch("chart_command_search.handlers.application.LaunchModalEffect")
@patch("chart_command_search.handlers.application.render_to_string", return_value="<html></html>")
@patch("chart_command_search.handlers.application.NoteType")
@patch("chart_command_search.handlers.application.Staff")
class TestChartSearchApp:
    def test_no_patient_id_returns_empty(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        app = _make_app(patient_id="")
        result = app.on_open()
        assert result == []

    def test_basic_open(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [_mock_obj(id="s1", first_name="Jane", last_name="Doe")]
        )
        mock_nt.objects.filter.return_value.order_by.return_value = [
            _mock_obj(dbid=5, name="Office Visit")
        ]
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app()
        result = app.on_open()

        assert result == "effect"
        mock_render.assert_called_once()
        ctx = mock_render.call_args[0][1]
        assert ctx["patient_id"] == "patient-uuid"
        assert len(ctx["providers"]) == 1
        assert ctx["providers"][0]["name"] == "Jane Doe"
        assert len(ctx["note_types"]) == 1
        assert ctx["note_types"][0]["name"] == "Office Visit"

    def test_staff_query_error(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.side_effect = RuntimeError("db error")
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app()
        result = app.on_open()
        assert result == "effect"

    def test_note_type_query_error(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )
        mock_nt.objects.filter.side_effect = RuntimeError("db error")
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app()
        result = app.on_open()
        assert result == "effect"

    def test_suggested_prompts_valid(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app(secrets={"SUGGESTED_PROMPTS": json.dumps(["What meds?", "Recent labs?"])})
        app.on_open()

        ctx = mock_render.call_args[0][1]
        assert ctx["practice_prompts"] == ["What meds?", "Recent labs?"]

    def test_suggested_prompts_invalid_json(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app(secrets={"SUGGESTED_PROMPTS": "not json"})
        app.on_open()

        ctx = mock_render.call_args[0][1]
        assert ctx["practice_prompts"] == []

    def test_suggested_prompts_empty_string(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app(secrets={"SUGGESTED_PROMPTS": ""})
        app.on_open()

        ctx = mock_render.call_args[0][1]
        assert ctx["practice_prompts"] == []

    def test_blank_staff_name_skipped(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: [
                _mock_obj(id="s1", first_name="", last_name=""),
                _mock_obj(id="s2", first_name="Jane", last_name="Doe"),
            ]
        )
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app()
        app.on_open()

        ctx = mock_render.call_args[0][1]
        assert len(ctx["providers"]) == 1
        assert ctx["providers"][0]["name"] == "Jane Doe"

    def test_suggested_prompts_not_a_list(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        mock_staff.objects.filter.return_value.order_by.return_value.__getitem__ = (
            lambda self, s: []
        )
        mock_nt.objects.filter.return_value.order_by.return_value = []
        mock_modal.return_value.apply.return_value = "effect"

        app = _make_app(secrets={"SUGGESTED_PROMPTS": json.dumps({"not": "a list"})})
        app.on_open()

        ctx = mock_render.call_args[0][1]
        assert ctx["practice_prompts"] == []

    def test_no_patient_key_in_context(
        self, mock_staff: Any, mock_nt: Any, mock_render: Any, mock_modal: Any
    ) -> None:
        from chart_command_search.handlers.application import ChartSearchApp

        app = ChartSearchApp.__new__(ChartSearchApp)
        event = MagicMock()
        event.context = {}
        app.event = event
        app.secrets = {}

        result = app.on_open()
        assert result == []
