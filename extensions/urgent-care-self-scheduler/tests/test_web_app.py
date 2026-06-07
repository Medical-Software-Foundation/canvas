import pathlib

import pytest
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin
from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError
from types import SimpleNamespace

from urgent_care_self_scheduler.handlers.web_app import UrgentCareWebApp

TEMPLATE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "urgent_care_self_scheduler"
    / "templates"
    / "wizard.html"
)


def _credentials(user: dict | None) -> SimpleNamespace:
    return SimpleNamespace(logged_in_user=user)


def test_web_app_uses_patient_session_auth_mixin() -> None:
    # Authentication is delegated to the SDK's mixin (idiomatic, easier to audit).
    assert issubclass(UrgentCareWebApp, PatientSessionAuthMixin)


def test_web_app_authenticate_accepts_patient() -> None:
    api = UrgentCareWebApp.__new__(UrgentCareWebApp)
    assert api.authenticate(_credentials({"type": "Patient", "id": "p-1"})) is True


def test_web_app_authenticate_rejects_staff() -> None:
    api = UrgentCareWebApp.__new__(UrgentCareWebApp)
    with pytest.raises(InvalidCredentialsError):
        api.authenticate(_credentials({"type": "Staff", "id": "s-1"}))


def test_path_is_wizard() -> None:
    assert UrgentCareWebApp.PATH == "/wizard"


def test_wizard_template_contains_form_sections() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    for needle in [
        "Reason for visit",
        "symptom",
        "Medications",
        "Allergies",
        "Pick a time",
        "Book appointment",
    ]:
        assert needle.lower() in html.lower(), f"missing section: {needle}"


def test_wizard_template_references_api_endpoints() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "/plugin-io/api/urgent_care_self_scheduler/api/me" in html
    assert "/plugin-io/api/urgent_care_self_scheduler/api/slots" in html
    assert "/plugin-io/api/urgent_care_self_scheduler/api/book" in html


def test_wizard_template_has_back_link_to_portal() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "back to portal" in html.lower() or "← back" in html.lower()
    # Patient portal lives at /app/ on Canvas.
    assert 'href="/app/"' in html


def test_wizard_template_has_success_pane_with_meeting_link_placeholder() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "meeting" in html.lower() or "join visit" in html.lower()
    assert "copy link" in html.lower()
