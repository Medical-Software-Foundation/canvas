"""Unit tests for the bundled templates loader."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from exam_chart_app.data import templates as templates_module
from exam_chart_app.data.templates import (
    get_hpi_template,
    load_default_templates,
)


@pytest.fixture(autouse=True)
def _reset_templates_cache():
    """Each test starts with a cold cache so the render_to_string mock
    actually fires and `assert_called_once_with` reflects this test's call."""
    templates_module._DEFAULT_TEMPLATES_CACHE = None
    yield
    templates_module._DEFAULT_TEMPLATES_CACHE = None


FAKE_TEMPLATES_JSON = json.dumps({
    "version": "1",
    "templates": {
        "default": {"hpi": "default hpi", "note": "", "letter": {"subject": "", "body": ""}},
        "K21.9": {"hpi": "gerd hpi", "note": "", "letter": {"subject": "", "body": ""}},
    },
})


@patch("exam_chart_app.data.templates.render_to_string")
def test_load_default_templates_returns_parsed_dict(mock_render):
    mock_render.return_value = FAKE_TEMPLATES_JSON
    result = load_default_templates()
    assert result["version"] == "1"
    assert "default" in result["templates"]
    assert "K21.9" in result["templates"]
    mock_render.assert_called_once_with("templates/default_templates.json")


@patch("exam_chart_app.data.templates.render_to_string")
def test_get_hpi_template_returns_match_for_known_code(mock_render):
    mock_render.return_value = FAKE_TEMPLATES_JSON
    assert get_hpi_template("K21.9") == "gerd hpi"


@patch("exam_chart_app.data.templates.render_to_string")
def test_get_hpi_template_falls_back_to_default_for_unknown_code(mock_render):
    mock_render.return_value = FAKE_TEMPLATES_JSON
    assert get_hpi_template("Z99.99") == "default hpi"


@patch("exam_chart_app.data.templates.render_to_string")
def test_get_hpi_template_falls_back_to_default_for_empty_code(mock_render):
    mock_render.return_value = FAKE_TEMPLATES_JSON
    assert get_hpi_template("") == "default hpi"
    assert get_hpi_template(None) == "default hpi"


@patch("exam_chart_app.data.templates.render_to_string")
def test_get_hpi_template_returns_empty_when_json_malformed(mock_render):
    mock_render.return_value = "not json"
    assert get_hpi_template("K21.9") == ""


@patch("exam_chart_app.data.templates.render_to_string")
def test_load_default_templates_is_cached(mock_render):
    """Second call uses the cached parse result; render_to_string fires once."""
    mock_render.return_value = FAKE_TEMPLATES_JSON
    first = load_default_templates()
    second = load_default_templates()
    assert first == second
    mock_render.assert_called_once_with("templates/default_templates.json")
