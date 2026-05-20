"""Unit tests for compound_medication_loader.applications.loader_app."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from compound_medication_loader.applications import loader_app as app_mod
from compound_medication_loader.applications.loader_app import CompoundMedicationLoaderApp


def test_on_open_renders_template_and_emits_modal_effect():
    app = CompoundMedicationLoaderApp.__new__(CompoundMedicationLoaderApp)

    with patch.object(app_mod, "render_to_string") as mock_render, \
         patch.object(app_mod, "LaunchModalEffect") as mock_modal:
        mock_render.return_value = "<html>ok</html>"
        modal_instance = MagicMock(name="modal-instance")
        mock_modal.return_value = modal_instance
        modal_instance.apply.return_value = "APPLIED"

        result = app.on_open()

        # 1. render_to_string called with the right template + api_base context
        assert mock_render.mock_calls == [
            call(
                "templates/loader.html",
                {"api_base": "/plugin-io/api/compound_medication_loader"},
            ),
        ]
        # 2. LaunchModalEffect class: one constructor call
        assert mock_modal.mock_calls == [
            call(
                content="<html>ok</html>",
                target=mock_modal.TargetType.DEFAULT_MODAL,
            ),
        ]
        # 3. modal_instance: .apply() is called on the returned object
        assert modal_instance.mock_calls == [call.apply()]

    assert result == "APPLIED"


def test_plugin_api_base_route_constant():
    assert (
        CompoundMedicationLoaderApp.PLUGIN_API_BASE_ROUTE
        == "/plugin-io/api/compound_medication_loader"
    )
