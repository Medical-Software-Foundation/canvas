# tests/applications/test_reporting_app.py
from __future__ import annotations

from reporting.applications.reporting_app import ReportingApp


def test_on_open_launches_full_page_modal():
    app = ReportingApp.__new__(ReportingApp)
    applied = app.on_open()
    effect = applied.owner  # stub .apply() wraps the effect as _Applied(owner)
    assert effect.url == "/plugin-io/api/reporting/app/home"
    assert effect.target == "page"
    assert effect.title == "Reporting"
