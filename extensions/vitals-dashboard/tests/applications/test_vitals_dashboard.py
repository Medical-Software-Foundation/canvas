"""Tests for vitals_dashboard/applications/vitals_dashboard.py."""

import json
from unittest.mock import MagicMock, patch

from vitals_dashboard.applications.vitals_dashboard import (
    VitalsDashboardApp,
    _ortho_row,
    _render_page,
)


class TestRenderPage:
    def test_bootstrap_replaced_into_html(self):
        bootstrap = json.dumps({"patient_key": "p-1", "staff_key": "s-1"})
        html = _render_page(bootstrap)
        assert "__BOOTSTRAP__" not in html
        assert '"patient_key": "p-1"' in html
        assert '"staff_key": "s-1"' in html

    def test_includes_chart_js_script(self):
        html = _render_page("{}")
        assert "chart.umd.min.js" in html

    def test_includes_root_container(self):
        html = _render_page("{}")
        assert 'id="vd-root"' in html


class TestOrthoRow:
    def test_contains_label_and_inputs(self):
        row = _ortho_row("Laying", "laying")
        assert "Laying" in row
        assert 'name="sys_laying"' in row
        assert 'name="dia_laying"' in row
        assert 'name="hr_laying"' in row

    def test_uses_numeric_inputs_with_ranges(self):
        row = _ortho_row("Standing", "standing")
        assert 'type="number"' in row
        assert 'max="300"' in row  # systolic + HR cap
        assert 'max="250"' in row  # diastolic cap


class TestAppOnOpen:
    def _make_app(self, context):
        app = VitalsDashboardApp.__new__(VitalsDashboardApp)
        app.event = MagicMock()
        app.event.context = context
        return app

    def test_happy_path_passes_patient_and_staff_ids(self):
        app = self._make_app({
            "patient": {"id": "patient-xyz"},
            "user": {"id": "staff-7"},
        })
        with patch(
            "vitals_dashboard.applications.vitals_dashboard.LaunchModalEffect"
        ) as mock_effect:
            mock_effect.TargetType.PAGE = "page"
            mock_effect.return_value.apply.return_value = "applied"

            result = app.on_open()

            assert result == "applied"
            (_, kwargs) = mock_effect.call_args
            assert kwargs["title"] == "Vitals"
            assert kwargs["target"] == "page"
            assert '"patient_key": "patient-xyz"' in kwargs["content"]
            assert '"staff_key": "staff-7"' in kwargs["content"]

    def test_missing_context_falls_back_to_blank(self):
        app = self._make_app(None)
        with patch(
            "vitals_dashboard.applications.vitals_dashboard.LaunchModalEffect"
        ) as mock_effect:
            mock_effect.TargetType.PAGE = "page"
            mock_effect.return_value.apply.return_value = "applied"

            app.on_open()

            (_, kwargs) = mock_effect.call_args
            assert '"patient_key": ""' in kwargs["content"]
            assert '"staff_key": ""' in kwargs["content"]

    def test_user_without_id_falls_back_to_staff_id(self):
        app = self._make_app({
            "patient": {"id": "pat-1"},
            "user": {"staff_id": "staff-alt"},
        })
        with patch(
            "vitals_dashboard.applications.vitals_dashboard.LaunchModalEffect"
        ) as mock_effect:
            mock_effect.TargetType.PAGE = "page"
            mock_effect.return_value.apply.return_value = "applied"

            app.on_open()

            (_, kwargs) = mock_effect.call_args
            assert '"staff_key": "staff-alt"' in kwargs["content"]

    def test_non_dict_context_safe(self):
        app = self._make_app("junk")
        with patch(
            "vitals_dashboard.applications.vitals_dashboard.LaunchModalEffect"
        ) as mock_effect:
            mock_effect.TargetType.PAGE = "page"
            mock_effect.return_value.apply.return_value = "applied"

            result = app.on_open()

            assert result == "applied"
            (_, kwargs) = mock_effect.call_args
            assert '"patient_key": ""' in kwargs["content"]
            assert '"staff_key": ""' in kwargs["content"]
