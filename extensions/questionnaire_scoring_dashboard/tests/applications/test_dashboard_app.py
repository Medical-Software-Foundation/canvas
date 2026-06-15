from unittest.mock import MagicMock

from questionnaire_scoring_dashboard.applications.dashboard_app import (
    ScoringDashboardApp,
)


def test_on_open_launches_page_for_patient():
    app = ScoringDashboardApp.__new__(ScoringDashboardApp)
    app.event = MagicMock()
    app.event.context = {"patient": {"id": "patient-99"}}
    effect = app.on_open()
    payload = effect.payload if hasattr(effect, "payload") else str(effect)
    assert "patient-99" in str(payload)
    assert "questionnaire_scoring_dashboard" in str(payload)
    assert '"target": "page"' in str(payload)
