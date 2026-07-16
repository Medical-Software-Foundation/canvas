"""Test for the PatientPanelApp Application handler (on_open)."""

__is_plugin__ = True

from patient_panel.applications.patient_panel_app import PatientPanelApp


class TestPatientPanelApp:
    def test_on_open_returns_launch_modal_effect_with_panel_url(self) -> None:
        app = PatientPanelApp.__new__(PatientPanelApp)
        effect = app.on_open()
        # Effect payload carries the modal URL (cache-busted).
        assert "/plugin-io/api/patient_panel/app/" in effect.payload
        assert "?v=" in effect.payload
