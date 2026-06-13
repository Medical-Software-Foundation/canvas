"""Tests for EHIExportApp — the global app-drawer entry point."""

import json

from ehi_export_tool.applications.ehi_app import EHIExportApp


def test_on_open_launches_full_page_workspace() -> None:
    """on_open returns a full-page modal effect pointing at the export workspace."""
    app = EHIExportApp.__new__(EHIExportApp)
    effect = app.on_open()

    data = json.loads(effect.payload)["data"]
    assert data["target"] == "page"
    assert data["url"].startswith("/plugin-io/api/ehi_export_tool/app/")
    assert "v=" in data["url"]  # cache-busted
    assert data["title"] == "EHI Export"
