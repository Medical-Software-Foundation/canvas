"""Tests for the static asset routes that serve canvas-plugin-ui assets."""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

from clinical_favorites.protocols.static_api import (
    FavoritesCSSAPI,
    FavoritesJSAPI,
    PluginUICSSAPI,
    PluginUIJSAPI,
)


@patch("clinical_favorites.protocols.static_api.render_to_string")
def test_css_route_returns_rendered_template_with_css_content_type(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = ":root { --primary, blue; }"

    api = PluginUICSSAPI(MagicMock())
    response_list = api.get()

    assert len(response_list) == 1
    response = response_list[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "text/css"
    assert response.content == b":root { --primary, blue; }"
    mock_render.assert_called_once_with("static/canvas-plugin-ui.css")


@patch("clinical_favorites.protocols.static_api.render_to_string")
def test_js_route_returns_rendered_template_with_javascript_content_type(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = "customElements.define('canvas-tabs', class {});"

    api = PluginUIJSAPI(MagicMock())
    response_list = api.get()

    assert len(response_list) == 1
    response = response_list[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "application/javascript"
    assert response.content == b"customElements.define('canvas-tabs', class {});"
    mock_render.assert_called_once_with("static/canvas-plugin-ui.js")


@patch("clinical_favorites.protocols.static_api.render_to_string")
def test_favorites_css_route_returns_rendered_template_with_css_content_type(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = ".header { padding: 0; }"

    api = FavoritesCSSAPI(MagicMock())
    response_list = api.get()

    assert len(response_list) == 1
    response = response_list[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "text/css"
    assert response.content == b".header { padding: 0; }"
    mock_render.assert_called_once_with("static/favorites.css")


@patch("clinical_favorites.protocols.static_api.render_to_string")
def test_favorites_js_route_returns_rendered_template_with_javascript_content_type(
    mock_render: MagicMock,
) -> None:
    mock_render.return_value = "const FAVORITES_SURFACE = 'manage';"

    api = FavoritesJSAPI(MagicMock())
    response_list = api.get()

    assert len(response_list) == 1
    response = response_list[0]
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "application/javascript"
    assert response.content == b"const FAVORITES_SURFACE = 'manage';"
    mock_render.assert_called_once_with("static/favorites.js")
