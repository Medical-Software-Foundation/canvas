"""Tests for ProfileWebApp."""

from contextlib import AbstractContextManager
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.template.engine import Engine

from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.handlers.simple_api.security import PatientSessionAuthMixin
from canvas_sdk.test_utils.factories import PatientFactory

from patient_portal_profile.handlers.profile_web_app import ProfileWebApp

PATIENT_ID = "patient-uuid-1234"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "patient_portal_profile"


def _render_template_direct(
    template_name: str, context: dict[str, Any] | None = None
) -> str:
    """Render a plugin template via Django's engine, bypassing the plugin-context decorator."""
    engine = Engine(dirs=[str(PLUGIN_DIR)])
    return engine.render_to_string(
        str(PLUGIN_DIR / template_name.lstrip("/")),
        context=context or {},
    )


def _make_patient(
    *,
    first_name: str = "Jane",
    last_name: str = "Doe",
    middle_name: str = "Q",
    suffix: str = "",
    birth_date: str = "1985-04-12",
    preferred_full_name: str = "Janie",
    photo_url: str = "https://cdn.example.com/avatar.png",
    user_email: str | None = "jane@example.com",
    user_phone: str | None = "+15551234567",
    user_is_portal: bool = True,
    addresses: list | None = None,
    preferred_pharmacy: dict | None = None,
) -> SimpleNamespace:
    """Build a fake Patient that mimics the SDK shape used by the handler.

    SimpleNamespace (not MagicMock) — Django's Variable resolver prefers
    __getitem__ over attribute access, and MagicMock auto-creates __getitem__.
    """
    if user_email is None:
        user: SimpleNamespace | None = None
    else:
        user = SimpleNamespace(
            email=user_email,
            phone_number=user_phone,
            is_portal_registered=user_is_portal,
        )

    addr_qs = MagicMock()
    addr_qs.all.return_value = addresses or []

    return SimpleNamespace(
        id=PATIENT_ID,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        suffix=suffix,
        birth_date=birth_date,
        preferred_full_name=preferred_full_name,
        photo_url=photo_url,
        preferred_pharmacy=preferred_pharmacy,
        user=user,
        addresses=addr_qs,
    )


def _patch_patient_lookup(patient: SimpleNamespace) -> AbstractContextManager[Any]:
    """Mock the Patient.objects.select_related().prefetch_related().get(...) chain."""
    return patch(
        "patient_portal_profile.handlers.profile_web_app.Patient.objects.select_related",
        return_value=MagicMock(
            prefetch_related=MagicMock(
                return_value=MagicMock(get=MagicMock(return_value=patient))
            )
        ),
    )


def _patch_care_team(rows: list[dict]) -> AbstractContextManager[Any]:
    """Mock the CareTeamMembership.objects.values(...).filter(...) chain."""
    filtered = MagicMock()
    filtered.__iter__ = lambda self: iter(rows)
    values = MagicMock()
    values.filter.return_value = filtered
    return patch(
        "patient_portal_profile.handlers.profile_web_app.CareTeamMembership.objects.values",
        return_value=values,
    )


def _patch_render() -> AbstractContextManager[Any]:
    """Replace canvas-sdk render_to_string with direct Django rendering of the real template."""
    return patch(
        "patient_portal_profile.handlers.profile_web_app.render_to_string",
        side_effect=_render_template_direct,
    )


def _make_app(headers: dict[str, str] | None = None) -> MagicMock:
    """Build a mock ProfileWebApp instance that bypasses SimpleAPI init."""
    app = MagicMock(spec=ProfileWebApp)
    app.request = MagicMock()
    app.request.headers = headers or {"canvas-logged-in-user-id": PATIENT_ID}
    return app


def _call_get_profile(app: MagicMock) -> tuple[bytes, int, str]:
    """Invoke get_profile and return (body, status_code, content_type)."""
    effects = ProfileWebApp.get_profile(app)
    assert len(effects) == 1
    response = effects[0]
    return (
        response.content or b"",
        response.status_code,
        (response.headers or {}).get("Content-Type", ""),
    )


def test_get_profile_renders_patient_data() -> None:
    """Happy path renders the patient's identity, contact, addresses, care team, and pharmacy."""
    address = SimpleNamespace(
        line1="123 Main St",
        line2="",
        city="Boston",
        state_code="MA",
        postal_code="02118",
        type="",
        get_use_display=lambda: "Home",
    )

    patient = _make_patient(
        addresses=[address],
        preferred_pharmacy={
            "pharmacy_name": "CVS Pharmacy #1234",
            "pharmacy_address": "500 Boylston St, Boston MA 02116",
            "pharmacy_phone_number": "(617) 555-0100",
            "pharmacy_ncpdp_id": "2382163",
            "default": True,
        },
    )
    care_team_rows = [
        {
            "staff__first_name": "Steven",
            "staff__last_name": "Magee",
            "staff__prefix": "Dr.",
            "staff__suffix": "",
            "staff__photos__url": "https://cdn.example.com/staff.png",
            "role_display": "Primary care physician",
        }
    ]

    with (
        _patch_patient_lookup(patient),
        _patch_care_team(care_team_rows),
        _patch_render(),
    ):
        body, status, content_type = _call_get_profile(_make_app())

    assert status == HTTPStatus.OK
    assert content_type == "text/html"
    html = body.decode()
    assert "Jane" in html and "Doe" in html
    assert "Janie" in html
    assert "1985-04-12" in html
    assert "jane@example.com" in html
    assert "+15551234567" in html
    assert "123 Main St" in html
    assert "Boston" in html
    assert "Dr. Steven Magee" in html
    assert "Primary care physician" in html
    assert "CVS Pharmacy #1234" in html
    assert "500 Boylston St, Boston MA 02116" in html
    assert "(617) 555-0100" in html
    assert 'src="https://cdn.example.com/avatar.png"' in html


def test_get_profile_uses_photo_url_from_patient() -> None:
    """The <img> src comes straight from Patient.photo_url — no manual fallback in template."""
    patient = _make_patient(photo_url="https://example.com/default-avatar.png")

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert 'src="https://example.com/default-avatar.png"' in body.decode()


def test_get_profile_omits_portal_section_when_no_user() -> None:
    """Patients with no associated CanvasUser don't get the registration block."""
    patient = _make_patient(user_email=None)

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert "Patient portal registration" not in body.decode()


def test_get_profile_omits_portal_section_when_user_not_portal_registered() -> None:
    """A CanvasUser that isn't portal-registered is treated as no portal user."""
    patient = _make_patient(user_is_portal=False)

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert "Patient portal registration" not in body.decode()


def test_get_profile_omits_phone_row_when_empty() -> None:
    """Empty phone number on the portal user hides the phone row but keeps email."""
    patient = _make_patient(user_phone="")

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    html = body.decode()
    assert "jane@example.com" in html
    assert "Phone" not in html


def test_get_profile_omits_addresses_section_when_empty() -> None:
    """No addresses → no Addresses section."""
    patient = _make_patient(addresses=[])

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert "Addresses" not in body.decode()


def test_get_profile_omits_care_team_section_when_empty() -> None:
    """No active care team members → no Care team section."""
    patient = _make_patient()

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert "Care team" not in body.decode()


def test_get_profile_omits_pharmacy_section_when_none() -> None:
    """No preferred pharmacy → no Preferred pharmacy section."""
    patient = _make_patient(preferred_pharmacy=None)

    with _patch_patient_lookup(patient), _patch_care_team([]), _patch_render():
        body, _, _ = _call_get_profile(_make_app())

    assert "Preferred pharmacy" not in body.decode()


def test_care_team_query_uses_single_values_call() -> None:
    """Guard against N+1: care team is fetched in a single .values().filter() chain."""
    patient = _make_patient()
    with (
        _patch_patient_lookup(patient),
        _patch_render(),
        patch(
            "patient_portal_profile.handlers.profile_web_app.CareTeamMembership.objects"
        ) as mock_objs,
    ):
        mock_objs.values.return_value.filter.return_value = iter([])
        ProfileWebApp.get_profile(_make_app())

    mock_objs.values.assert_called_once_with(
        "staff__first_name",
        "staff__last_name",
        "staff__prefix",
        "staff__suffix",
        "staff__photos__url",
        "role_display",
    )


def test_get_main_js_returns_javascript_content_type() -> None:
    """main.js is served as text/javascript."""
    with _patch_render():
        effects = ProfileWebApp.get_main_js(MagicMock(spec=ProfileWebApp))

    assert len(effects) == 1
    response = effects[0]
    assert response.status_code == HTTPStatus.OK
    assert (response.headers or {}).get("Content-Type") == "text/javascript"
    assert response.content is not None and len(response.content) > 0


def test_get_styles_css_returns_css_content_type() -> None:
    """styles.css is served as text/css."""
    with _patch_render():
        effects = ProfileWebApp.get_styles_css(MagicMock(spec=ProfileWebApp))

    assert len(effects) == 1
    response = effects[0]
    assert response.status_code == HTTPStatus.OK
    assert (response.headers or {}).get("Content-Type") == "text/css"
    assert response.content is not None and len(response.content) > 0


def test_authenticate_rejects_staff_session() -> None:
    """PatientSessionAuthMixin must refuse logged-in staff users."""
    mixin = PatientSessionAuthMixin()
    credentials = MagicMock(logged_in_user={"id": "staff-1", "type": "Staff"})

    with pytest.raises(InvalidCredentialsError):
        mixin.authenticate(credentials)


def test_authenticate_accepts_patient_session() -> None:
    """PatientSessionAuthMixin admits logged-in patient sessions."""
    mixin = PatientSessionAuthMixin()
    credentials = MagicMock(logged_in_user={"id": PATIENT_ID, "type": "Patient"})

    assert mixin.authenticate(credentials) is True


@pytest.mark.django_db
def test_get_profile_with_real_patient_factory() -> None:
    """End-to-end smoke test against the test DB using PatientFactory."""
    patient = PatientFactory.create()
    app = _make_app(headers={"canvas-logged-in-user-id": str(patient.id)})

    with _patch_care_team([]), _patch_render():
        body, status, content_type = _call_get_profile(app)

    assert status == HTTPStatus.OK
    assert content_type == "text/html"
    html = body.decode()
    assert patient.first_name in html
    assert patient.last_name in html
