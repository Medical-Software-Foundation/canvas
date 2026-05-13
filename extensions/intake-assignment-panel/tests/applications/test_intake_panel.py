"""Tests for the IntakePanelApp Application."""

from unittest.mock import patch

from applications.intake_panel import IntakePanelApp


class TestIntakePanelApp:
    @patch("applications.intake_panel.LaunchModalEffect")
    def test_on_open_launches_modal_at_app_url(self, mock_effect_cls):
        mock_effect_cls.TargetType.PAGE = "page"
        mock_effect_cls.return_value.apply.return_value = "effect-result"

        app = IntakePanelApp.__new__(IntakePanelApp)
        result = app.on_open()

        assert result == "effect-result"
        mock_effect_cls.assert_called_once_with(
            url="/plugin-io/api/intake_assignment_panel/app/",
            target="page",
        )
        mock_effect_cls.return_value.apply.assert_called_once_with()
