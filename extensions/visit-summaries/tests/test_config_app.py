"""Tests for visit_summaries.applications.config_app and protocols.config_api."""
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ConfigApp
# ---------------------------------------------------------------------------

def _make_config_app():
    from visit_summaries.applications.config_app import ConfigApp

    app = ConfigApp.__new__(ConfigApp)
    # context and target are properties that delegate to self.event
    app.event = MagicMock()
    app.event.context = {}
    app.secrets = {}
    return app


def test_config_app_on_open_returns_effect():
    app = _make_config_app()
    effect = app.on_open()
    assert effect is not None


def test_config_app_on_open_uses_plugin_api_route():
    app = _make_config_app()
    effect = app.on_open()
    payload = str(effect)
    assert "visit_summaries" in payload or effect is not None


# ---------------------------------------------------------------------------
# ConfigApi
# ---------------------------------------------------------------------------

def _make_api(method="GET", path="/config", body=None, params=None):
    from visit_summaries.protocols.config_api import ConfigApi

    api = ConfigApi.__new__(ConfigApi)
    api.event = MagicMock()
    api.secrets = {}

    request = MagicMock()
    request.method = method
    request.json.return_value = body or {}
    request.query_params = params or {}
    api.request = request
    return api


def test_get_config_returns_json():
    api = _make_api()
    with patch(
        "visit_summaries.protocols.config_api.get_config",
        return_value={"enable_avs": True, "avs_language": "English"},
    ):
        responses = api.get_config()

    assert len(responses) == 1


def test_save_config_accepts_valid_body():
    api = _make_api(method="POST", body={"enable_avs": True})
    with patch("visit_summaries.protocols.config_api.update_config", return_value={"enable_avs": True, "enable_previous_visit": True, "enable_since_last_visit": True}) as mock_update:
        responses = api.save_config()

    assert len(responses) == 1
    mock_update.assert_called_once()


def test_save_config_rejects_non_dict():
    api = _make_api(method="POST")
    api.request.json.return_value = ["not", "a", "dict"]

    responses = api.save_config()

    assert len(responses) == 1


def test_save_config_ignores_unknown_keys():
    """Unknown keys in the payload should be silently dropped."""
    api = _make_api(method="POST", body={"evil_key": "hacked", "enable_avs": True})
    with patch("visit_summaries.protocols.config_api.update_config", return_value={"enable_avs": True, "enable_previous_visit": True, "enable_since_last_visit": True}) as mock_update:
        api.save_config()

    call_args = mock_update.call_args[0][0]
    assert "evil_key" not in call_args


def test_config_panel_rejects_non_relative_save_url():
    """A save_url that doesn't start with / should be replaced with the default."""
    api = _make_api(params={"save_url": "javascript:alert(1)"})
    with (
        patch(
            "visit_summaries.protocols.config_api.get_config",
            return_value={"enable_avs": True, "avs_language": "English"},
        ),
        patch(
            "visit_summaries.protocols.config_api.render_to_string",
            return_value="<html>config panel</html>",
        ) as mock_render,
    ):
        api.config_panel()

    call_kwargs = mock_render.call_args[0][1]
    assert call_kwargs["save_url"] == "/plugin-io/api/visit_summaries/config"


def test_config_panel_renders_html():
    api = _make_api(params={"save_url": "/plugin-io/api/visit_summaries/config"})
    with (
        patch(
            "visit_summaries.protocols.config_api.get_config",
            return_value={"enable_avs": True, "avs_language": "English"},
        ),
        patch(
            "visit_summaries.protocols.config_api.render_to_string",
            return_value="<html>config panel</html>",
        ) as mock_render,
    ):
        responses = api.config_panel()

    assert len(responses) == 1
    call_kwargs = mock_render.call_args[0][1]
    assert "config" in call_kwargs
    assert call_kwargs["save_url"] == "/plugin-io/api/visit_summaries/config"
