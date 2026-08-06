from http import HTTPStatus
from unittest.mock import MagicMock, patch


class TestStaticApi:
    def test_plugin_ui_css_returns_css_response(self):
        """CSS endpoint serves the rendered template with text/css content type."""
        from rx_history.protocols.static_api import StaticApi

        with patch(
            "rx_history.protocols.static_api.render_to_string"
        ) as mock_render:
            mock_render.return_value = "body { color: red; }"

            handler = StaticApi(event=MagicMock())
            results = handler.plugin_ui_css()

            assert len(results) == 1
            response = results[0]
            assert response.status_code == HTTPStatus.OK
            assert response.content == b"body { color: red; }"
            mock_render.assert_called_once_with("static/canvas-plugin-ui.css")

    def test_plugin_ui_js_returns_js_response(self):
        """JS endpoint serves the rendered template with application/javascript content type."""
        from rx_history.protocols.static_api import StaticApi

        with patch(
            "rx_history.protocols.static_api.render_to_string"
        ) as mock_render:
            mock_render.return_value = "window.foo = 1;"

            handler = StaticApi(event=MagicMock())
            results = handler.plugin_ui_js()

            assert len(results) == 1
            response = results[0]
            assert response.status_code == HTTPStatus.OK
            assert response.content == b"window.foo = 1;"
            mock_render.assert_called_once_with("static/canvas-plugin-ui.js")
