"""Tests for the RecentLabsApp Application handler."""

from unittest.mock import MagicMock, patch

from canvas_sdk.effects import Effect

from recent_labs.applications.recent_labs_app import RecentLabsApp


def _app(context):
    app = MagicMock(spec=RecentLabsApp)
    app.secrets = {}
    app.event = MagicMock()
    app.event.context = context
    return app


class TestRecentLabsAppOnOpen:
    def test_returns_launch_modal_effect_with_grouped_values(self):
        app = _app({"patient": {"id": "patient-123"}})

        fake_groups = [
            {"test_name": "A1c", "results": [{}, {}]},
            {"test_name": "Covid", "results": [{}]},
        ]
        with patch("recent_labs.applications.recent_labs_app.get_recent_results_by_test",
                   return_value=fake_groups) as mock_query, \
             patch("recent_labs.applications.recent_labs_app.render_to_string",
                   return_value="<html>ok</html>") as mock_render, \
             patch("recent_labs.applications.recent_labs_app.log"):
            result = RecentLabsApp.on_open(app)

        mock_query.assert_called_once_with("patient-123")
        ctx = mock_render.call_args.args[1]
        assert ctx["patient_id"] == "patient-123"
        assert ctx["has_values"] is True
        assert ctx["lab_groups"] == fake_groups
        assert isinstance(result, Effect)
        assert "LAUNCH_MODAL" in str(result)

    def test_empty_state_when_no_values(self):
        app = _app({"patient": {"id": "patient-123"}})

        with patch("recent_labs.applications.recent_labs_app.get_recent_results_by_test",
                   return_value=[]), \
             patch("recent_labs.applications.recent_labs_app.render_to_string",
                   return_value="<html>empty</html>") as mock_render, \
             patch("recent_labs.applications.recent_labs_app.log"):
            result = RecentLabsApp.on_open(app)

        ctx = mock_render.call_args.args[1]
        assert ctx["has_values"] is False
        assert ctx["lab_groups"] == []
        assert isinstance(result, Effect)

    def test_returns_empty_list_when_no_patient_id(self):
        app = _app({"patient": {}})

        with patch("recent_labs.applications.recent_labs_app.log"):
            result = RecentLabsApp.on_open(app)

        assert result == []
