"""Tests for VaccineCardWebApp."""

from contextlib import AbstractContextManager
from datetime import date
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.template.engine import Engine

from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.handlers.simple_api.security import PatientSessionAuthMixin
from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data.immunization import (
    Immunization,
    ImmunizationCoding,
    ImmunizationStatement,
    ImmunizationStatementCoding,
)
from canvas_sdk.v1.data.patient import Patient

from portal_vaccine_card.handlers import vaccine_card_web_app
from portal_vaccine_card.handlers.vaccine_card_web_app import (
    VaccineCardWebApp,
    _build_rows,
)

PATIENT_ID = "patient-uuid-1234"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "portal_vaccine_card"

CVX_SYSTEM = "http://hl7.org/fhir/sid/cvx"


# ---------------------------------------------------------------------------
# Rendering helpers (mirror patient-portal-profile conventions)
# ---------------------------------------------------------------------------
def _render_template_direct(
    template_name: str, context: dict[str, Any] | None = None
) -> str:
    """Render a plugin template via Django's engine, bypassing the plugin-context decorator."""
    engine = Engine(dirs=[str(PLUGIN_DIR)])
    return engine.render_to_string(
        str(PLUGIN_DIR / template_name.lstrip("/")),
        context=context or {},
    )


def _patch_render() -> AbstractContextManager[Any]:
    """Replace canvas-sdk render_to_string with direct Django rendering of the real template."""
    return patch(
        "portal_vaccine_card.handlers.vaccine_card_web_app.render_to_string",
        side_effect=_render_template_direct,
    )


def _patch_patient_lookup(
    preferred_full_name: str = "Jane Doe",
) -> AbstractContextManager[Any]:
    """Mock Patient.objects.get to return a minimal patient namespace."""
    patient = SimpleNamespace(id=PATIENT_ID, preferred_full_name=preferred_full_name)
    return patch(
        "portal_vaccine_card.handlers.vaccine_card_web_app.Patient.objects.get",
        return_value=patient,
    )


def _patch_rows(rows: list[dict[str, Any]]) -> AbstractContextManager[Any]:
    """Mock _build_rows to return canned rows."""
    return patch(
        "portal_vaccine_card.handlers.vaccine_card_web_app._build_rows",
        return_value=rows,
    )


def _make_app(headers: dict[str, str] | None = None) -> MagicMock:
    """Build a mock VaccineCardWebApp instance that bypasses SimpleAPI init."""
    app = MagicMock(spec=VaccineCardWebApp)
    app.request = MagicMock()
    app.request.headers = headers or {"canvas-logged-in-user-id": PATIENT_ID}
    return app


def _call_get_card(app: MagicMock) -> tuple[bytes, int, str]:
    """Invoke get_card and return (body, status_code, content_type)."""
    effects = VaccineCardWebApp.get_card(app)
    assert len(effects) == 1
    response = effects[0]
    return (
        response.content or b"",
        response.status_code,
        (response.headers or {}).get("Content-Type", ""),
    )


def _row(**overrides: Any) -> dict[str, Any]:
    """Build a vaccine row with sensible defaults (mirrors _build_rows output)."""
    d = overrides.pop("date", date(2024, 10, 1))
    row = {
        "name": "Influenza, seasonal",
        "date": d,
        "date_display": d.isoformat() if d else "",
        "source": "Administered here",
        "manufacturer": "",
        "lot_number": "",
        "route": "",
        "comment": "",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Template / get_card rendering tests
# ---------------------------------------------------------------------------
def test_get_card_renders_vaccine_rows() -> None:
    """Happy path renders the patient name and each vaccine row with its source badge."""
    rows = [
        _row(name="Influenza, seasonal", source="Administered here"),
        _row(name="Tetanus", source="Reported history", date=date(2010, 5, 2)),
    ]

    with _patch_patient_lookup("Jane Doe"), _patch_rows(rows), _patch_render():
        body, status, content_type = _call_get_card(_make_app())

    assert status == HTTPStatus.OK
    assert content_type == "text/html"
    html = body.decode()
    assert "Vaccine Record" in html
    assert "Jane Doe" in html
    assert "Influenza, seasonal" in html
    assert "Tetanus" in html
    assert "Administered here" in html
    assert "Reported history" in html
    assert "2024-10-01" in html


def test_get_card_shows_optional_details_only_when_present() -> None:
    """Manufacturer / lot / route / comment render only when populated — never as 'None'."""
    rows = [
        _row(
            name="COVID-19",
            manufacturer="Pfizer",
            lot_number="ABC123",
            route="Intramuscular",
        ),
        _row(name="Hepatitis B", source="Reported history", comment="Series complete"),
    ]

    with _patch_patient_lookup(), _patch_rows(rows), _patch_render():
        body, _, _ = _call_get_card(_make_app())

    html = body.decode()
    assert "Pfizer" in html
    assert "ABC123" in html
    assert "Intramuscular" in html
    assert "Series complete" in html
    # The empty fields on the second row must not leak placeholder text.
    assert "None" not in html
    assert "Manufacturer:" in html  # present for the first row only
    assert html.count("Manufacturer:") == 1


def test_get_card_renders_undated_row_without_none() -> None:
    """A row with no date renders a friendly label, not 'None'."""
    rows = [_row(name="Polio", date=None)]

    with _patch_patient_lookup(), _patch_rows(rows), _patch_render():
        body, _, _ = _call_get_card(_make_app())

    html = body.decode()
    assert "Polio" in html
    assert "Date not recorded" in html
    assert "None" not in html


def test_get_card_renders_empty_state() -> None:
    """A patient with no immunizations sees the empty-state message and no print button."""
    with _patch_patient_lookup(), _patch_rows([]), _patch_render():
        body, _, _ = _call_get_card(_make_app())

    html = body.decode()
    assert "No immunizations on file." in html
    assert "print-button" not in html


def test_get_card_resolves_patient_from_session_header() -> None:
    """The patient id used for the lookup comes from the session header, never the client."""
    rows: list[dict[str, Any]] = []
    with (
        _patch_render(),
        _patch_rows(rows) as build_rows,
        patch(
            "portal_vaccine_card.handlers.vaccine_card_web_app.Patient.objects.get"
        ) as patient_get,
    ):
        patient_get.return_value = SimpleNamespace(preferred_full_name="X")
        VaccineCardWebApp.get_card(
            _make_app({"canvas-logged-in-user-id": "session-pt-9"})
        )

    patient_get.assert_called_once_with(id="session-pt-9")
    build_rows.assert_called_once_with("session-pt-9")


def test_get_card_returns_404_when_patient_missing() -> None:
    """An unknown session patient yields a clean 404, not a 500."""
    with (
        _patch_render(),
        _patch_rows([]) as build_rows,
        patch(
            "portal_vaccine_card.handlers.vaccine_card_web_app.Patient.objects.get",
            side_effect=Patient.DoesNotExist,
        ),
    ):
        body, status, content_type = _call_get_card(_make_app())

    assert status == HTTPStatus.NOT_FOUND
    assert content_type == "text/plain"
    assert b"Patient not found" in body
    # No point building rows if the patient lookup failed.
    build_rows.assert_not_called()


# ---------------------------------------------------------------------------
# Static asset tests
# ---------------------------------------------------------------------------
def test_get_main_js_returns_javascript_content_type() -> None:
    """main.js is served as text/javascript."""
    with _patch_render():
        effects = VaccineCardWebApp.get_main_js(MagicMock(spec=VaccineCardWebApp))

    assert len(effects) == 1
    response = effects[0]
    assert response.status_code == HTTPStatus.OK
    assert (response.headers or {}).get("Content-Type") == "text/javascript"
    assert response.content is not None and len(response.content) > 0


def test_get_styles_css_returns_css_content_type() -> None:
    """styles.css is served as text/css."""
    with _patch_render():
        effects = VaccineCardWebApp.get_styles_css(MagicMock(spec=VaccineCardWebApp))

    assert len(effects) == 1
    response = effects[0]
    assert response.status_code == HTTPStatus.OK
    assert (response.headers or {}).get("Content-Type") == "text/css"
    assert response.content is not None and len(response.content) > 0


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# _best_display unit tests
# ---------------------------------------------------------------------------
def test_best_display_prefers_cvx_coding() -> None:
    """When multiple codings exist, the CVX one wins."""
    codings = [
        SimpleNamespace(
            system="http://snomed.info/sct", code="111", display="SNOMED name"
        ),
        SimpleNamespace(system=CVX_SYSTEM, code="140", display="Influenza, seasonal"),
    ]
    assert vaccine_card_web_app._best_display(codings) == "Influenza, seasonal"


def test_best_display_falls_back_to_code_then_default() -> None:
    """Missing display falls back to code; no codings falls back to the default label."""
    assert (
        vaccine_card_web_app._best_display(
            [SimpleNamespace(system=CVX_SYSTEM, code="140", display="")]
        )
        == "140"
    )
    assert vaccine_card_web_app._best_display([]) == "Immunization"


# ---------------------------------------------------------------------------
# Real-DB tests for _build_rows (merge / filter / sort / scope)
# ---------------------------------------------------------------------------
def _create_immunization(
    patient: Any,
    *,
    display: str,
    date_ordered: date | None,
    status: str = "in-progress",
    deleted: bool = False,
    manufacturer: str = "",
    lot_number: str = "",
    route: str = "",
) -> Immunization:
    imm = Immunization.objects.create(
        patient=patient,
        note=NoteFactory.create(),
        status=status,
        deleted=deleted,
        date_ordered=date_ordered,
        manufacturer=manufacturer,
        lot_number=lot_number,
        route=route,
    )
    ImmunizationCoding.objects.create(
        immunization=imm, system=CVX_SYSTEM, code="140", display=display
    )
    return imm


def _create_statement(
    patient: Any,
    *,
    display: str,
    statement_date: date | None,
    deleted: bool = False,
    comment: str = "",
) -> ImmunizationStatement:
    stmt = ImmunizationStatement.objects.create(
        patient=patient,
        note=NoteFactory.create(),
        deleted=deleted,
        date=statement_date,
        comment=comment,
    )
    ImmunizationStatementCoding.objects.create(
        immunization_statement=stmt, system=CVX_SYSTEM, code="08", display=display
    )
    return stmt


@pytest.mark.django_db
def test_build_rows_merges_sorts_and_tags_sources() -> None:
    """Administered immunizations and reported statements merge, newest first, undated last."""
    patient = PatientFactory.create()
    pid = str(patient.id)

    _create_immunization(patient, display="Influenza", date_ordered=date(2024, 1, 1))
    _create_statement(patient, display="Tetanus", statement_date=date(2022, 6, 1))
    _create_immunization(patient, display="Polio", date_ordered=None)
    _create_statement(patient, display="MMR", statement_date=date(2023, 9, 1))

    rows = _build_rows(pid)

    assert [r["name"] for r in rows] == ["Influenza", "MMR", "Tetanus", "Polio"]
    assert rows[0]["source"] == "Administered here"
    assert rows[1]["source"] == "Reported history"
    # Undated row sorted last.
    assert rows[-1]["name"] == "Polio"
    assert rows[-1]["date"] is None


@pytest.mark.django_db
def test_build_rows_includes_in_progress_and_excludes_deleted() -> None:
    """Administered immunizations show regardless of status (a committed Immunize command
    keeps the default ``in-progress`` status); soft-deleted records are excluded."""
    patient = PatientFactory.create()
    pid = str(patient.id)

    # Regression: an Immunize command commits with status "in-progress", not "completed".
    _create_immunization(
        patient,
        display="In progress imm",
        date_ordered=date(2024, 1, 1),
        status="in-progress",
    )
    _create_immunization(
        patient,
        display="Completed imm",
        date_ordered=date(2024, 2, 1),
        status="completed",
    )
    _create_immunization(
        patient, display="Deleted imm", date_ordered=date(2024, 3, 1), deleted=True
    )
    _create_statement(
        patient, display="Keep statement", statement_date=date(2023, 1, 1)
    )
    _create_statement(
        patient,
        display="Deleted statement",
        statement_date=date(2023, 2, 1),
        deleted=True,
    )

    names = {r["name"] for r in _build_rows(pid)}

    assert names == {"In progress imm", "Completed imm", "Keep statement"}


@pytest.mark.django_db
def test_build_rows_is_scoped_to_the_patient() -> None:
    """Another patient's immunization records never appear."""
    me = PatientFactory.create()
    other = PatientFactory.create()

    _create_immunization(me, display="Mine", date_ordered=date(2024, 1, 1))
    _create_immunization(other, display="Theirs", date_ordered=date(2024, 1, 1))
    _create_statement(other, display="Theirs too", statement_date=date(2024, 1, 1))

    names = {r["name"] for r in _build_rows(str(me.id))}

    assert names == {"Mine"}


@pytest.mark.django_db
def test_build_rows_carries_optional_immunization_details() -> None:
    """Manufacturer / lot / route survive onto the administered row; statement carries its comment."""
    patient = PatientFactory.create()
    pid = str(patient.id)

    _create_immunization(
        patient,
        display="COVID-19",
        date_ordered=date(2024, 1, 1),
        manufacturer="Pfizer",
        lot_number="ABC123",
        route="Intramuscular",
    )
    _create_statement(
        patient,
        display="Hep B",
        statement_date=date(2023, 1, 1),
        comment="Series complete",
    )

    rows = _build_rows(pid)
    administered = next(r for r in rows if r["name"] == "COVID-19")
    reported = next(r for r in rows if r["name"] == "Hep B")

    assert administered["manufacturer"] == "Pfizer"
    assert administered["lot_number"] == "ABC123"
    assert administered["route"] == "Intramuscular"
    assert reported["comment"] == "Series complete"


@pytest.mark.django_db
def test_get_card_end_to_end_with_real_records() -> None:
    """End-to-end: real patient + records render through the real template."""
    patient = PatientFactory.create()
    _create_immunization(
        patient, display="Influenza, seasonal", date_ordered=date(2024, 1, 1)
    )

    app = _make_app(headers={"canvas-logged-in-user-id": str(patient.id)})

    with _patch_render():
        body, status, content_type = _call_get_card(app)

    assert status == HTTPStatus.OK
    assert content_type == "text/html"
    html = body.decode()
    assert "Influenza, seasonal" in html
    assert "Administered here" in html
    assert "None" not in html
