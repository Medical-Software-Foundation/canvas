"""Unit tests for the narratives AttributeHub store."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from exam_chart_app.data import narratives


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_set_narrative_writes_attribute(mock_hub_model):
    hub = MagicMock()
    mock_hub_model.objects.get_or_create.return_value = (hub, True)
    narratives.set_narrative("cmd-uuid-1", "Patient reports cough x3d.")
    mock_hub_model.objects.get_or_create.assert_called_once_with(
        type="canvas__exam_chart_app", id="cmd-uuid-1",
    )
    hub.set_attribute.assert_called_once_with("narrative", "Patient reports cough x3d.")


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_set_narrative_noop_for_empty_command_uuid(mock_hub_model):
    narratives.set_narrative("", "any")
    mock_hub_model.objects.get_or_create.assert_not_called()


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_get_narrative_returns_empty_when_no_hub(mock_hub_model):
    mock_hub_model.objects.filter.return_value.first.return_value = None
    assert narratives.get_narrative("cmd-uuid-1") == ""


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_get_narrative_returns_stored_value(mock_hub_model):
    hub = MagicMock()
    hub.get_attribute.return_value = "stored text"
    mock_hub_model.objects.filter.return_value.first.return_value = hub
    assert narratives.get_narrative("cmd-uuid-1") == "stored text"
    mock_hub_model.objects.filter.assert_called_once_with(
        type="canvas__exam_chart_app", id="cmd-uuid-1",
    )
    hub.get_attribute.assert_called_once_with("narrative")


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_get_narrative_returns_empty_for_non_string_value(mock_hub_model):
    """AttributeHub.get_attribute may return non-str on legacy rows."""
    hub = MagicMock()
    hub.get_attribute.return_value = None
    mock_hub_model.objects.filter.return_value.first.return_value = hub
    assert narratives.get_narrative("cmd-uuid-1") == ""


@patch("exam_chart_app.data.narratives.AttributeHub")
def test_get_narrative_noop_for_empty_command_uuid(mock_hub_model):
    assert narratives.get_narrative("") == ""
    mock_hub_model.objects.filter.assert_not_called()
