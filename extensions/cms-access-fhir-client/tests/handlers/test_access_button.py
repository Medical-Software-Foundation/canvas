"""Tests for the ACCESS chart-header button."""
from unittest.mock import MagicMock, patch


def _make_button(patient_id):
    from cms_access_fhir_client.handlers.access_button import AccessInspectorButton

    btn = AccessInspectorButton.__new__(AccessInspectorButton)
    btn.event = MagicMock()
    btn.event.target.id = patient_id
    return btn


class TestAccessInspectorButton:
    def test_metadata(self):
        from canvas_sdk.handlers.action_button import ActionButton
        from cms_access_fhir_client.handlers.access_button import AccessInspectorButton

        assert AccessInspectorButton.BUTTON_TITLE == "ACCESS"
        assert AccessInspectorButton.BUTTON_BACKGROUND_COLOR == "#0D2499"
        assert AccessInspectorButton.BUTTON_TEXT_COLOR == "#FFFFFF"
        assert AccessInspectorButton.BUTTON_LOCATION == ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def test_handle_renders_inline_modal_with_patient_id(self):
        btn = _make_button("patient-9")
        captured = {}

        def fake_render(template, ctx=None):
            if template == "static/index.html":
                captured["ctx"] = ctx
                return f"<html>{ctx.get('patient_id')}</html>"
            return f"/* {template} */"

        with patch("cms_access_fhir_client.handlers.access_button.render_to_string", side_effect=fake_render):
            effects = btn.handle()

        assert captured["ctx"]["patient_id"] == "patient-9"
        assert "patient-9" in str(effects[0].payload)

    def test_handle_returns_empty_without_patient(self):
        btn = _make_button(None)
        assert btn.handle() == []
