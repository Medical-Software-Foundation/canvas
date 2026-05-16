"""Unit tests for ExamSectionAdditionalFieldsHandler.

Verifies the COMMAND__FORM__GET_ADDITIONAL_FIELDS handler that bridges
plugin-stashed narratives back into the chart's metadata-form UI for
ROS / PE commands.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from exam_chart_app.protocols.additional_fields import (
    ExamSectionAdditionalFieldsHandler,
    NARRATIVE_KEY,
    NARRATIVE_LABEL,
)


def _make_handler(schema_key: str, command_uuid: str | None = "cmd-uuid-1"):
    handler = ExamSectionAdditionalFieldsHandler.__new__(
        ExamSectionAdditionalFieldsHandler
    )
    event = MagicMock()
    event.context = {"schema_key": schema_key}
    event.target.id = command_uuid
    handler.event = event
    return handler


@patch("exam_chart_app.protocols.additional_fields.CommandMetadataCreateFormEffect")
@patch("exam_chart_app.protocols.additional_fields.get_narrative")
def test_ros_schema_emits_narrative_field_with_stored_value(
    mock_get_narrative, mock_effect_cls,
):
    mock_get_narrative.return_value = "ROS narrative text"
    mock_effect_cls.return_value.apply.return_value = "EFFECT"

    result = _make_handler("ros").compute()

    assert result == ["EFFECT"]
    mock_get_narrative.assert_called_once_with("cmd-uuid-1")
    mock_effect_cls.assert_called_once()
    kwargs = mock_effect_cls.call_args.kwargs
    assert kwargs["command_uuid"] == "cmd-uuid-1"
    fields = kwargs["form_fields"]
    assert len(fields) == 1
    field = fields[0]
    assert field.key == NARRATIVE_KEY
    assert field.label == NARRATIVE_LABEL
    assert field.value == "ROS narrative text"
    assert field.required is False
    assert field.editable is True


@patch("exam_chart_app.protocols.additional_fields.CommandMetadataCreateFormEffect")
@patch("exam_chart_app.protocols.additional_fields.get_narrative")
def test_exam_schema_emits_narrative_field(mock_get_narrative, mock_effect_cls):
    mock_get_narrative.return_value = "PE narrative text"
    mock_effect_cls.return_value.apply.return_value = "EFFECT"

    result = _make_handler("exam").compute()

    assert result == ["EFFECT"]
    mock_get_narrative.assert_called_once_with("cmd-uuid-1")


@patch("exam_chart_app.protocols.additional_fields.CommandMetadataCreateFormEffect")
@patch("exam_chart_app.protocols.additional_fields.get_narrative")
def test_unsupported_schema_returns_empty(mock_get_narrative, mock_effect_cls):
    result = _make_handler("prescribe").compute()
    assert result == []
    mock_get_narrative.assert_not_called()
    mock_effect_cls.assert_not_called()


@patch("exam_chart_app.protocols.additional_fields.CommandMetadataCreateFormEffect")
@patch("exam_chart_app.protocols.additional_fields.get_narrative")
def test_missing_schema_key_returns_empty(mock_get_narrative, mock_effect_cls):
    handler = ExamSectionAdditionalFieldsHandler.__new__(
        ExamSectionAdditionalFieldsHandler
    )
    event = MagicMock()
    event.context = {}
    handler.event = event

    assert handler.compute() == []
    mock_get_narrative.assert_not_called()
    mock_effect_cls.assert_not_called()


@patch("exam_chart_app.protocols.additional_fields.CommandMetadataCreateFormEffect")
@patch("exam_chart_app.protocols.additional_fields.get_narrative")
def test_missing_command_uuid_skips_narrative_lookup(
    mock_get_narrative, mock_effect_cls,
):
    """Falsy command_uuid → render an empty narrative field, no DB read."""
    mock_effect_cls.return_value.apply.return_value = "EFFECT"

    result = _make_handler("ros", command_uuid=None).compute()

    assert result == ["EFFECT"]
    mock_get_narrative.assert_not_called()
    field = mock_effect_cls.call_args.kwargs["form_fields"][0]
    assert field.value == ""
