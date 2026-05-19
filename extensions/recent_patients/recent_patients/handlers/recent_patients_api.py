from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient

from recent_patients import CACHE_BUST as _CACHE_BUST
from recent_patients.models.recent_patient_interaction import RecentPatientInteraction

ROW_LIMIT = 50


def _staff_id_candidates(staff_id: str) -> set[str]:
    """All UUID-shaped forms of `staff_id` that should match a stored row.

    `Staff.id` is a UUIDField, so `str(staff.id)` always emits the canonical
    dashed form on the write side. The `canvas-logged-in-user-id` header
    can arrive in either dashed or undashed form depending on session
    conditions. Our `staff_id` column is a `TextField` (byte-exact match,
    no UUID-aware normalization), so we must put both forms in the
    candidate set regardless of which form the header had.

    The naive `{value, value.replace("-", "")}` only generates two forms
    when the input is dashed; an undashed input yields a one-element set
    that doesn't contain the dashed form stored in the DB. Parsing through
    `uuid.UUID()` produces the canonical dashed form no matter what.
    """
    candidates: set[str] = {staff_id, staff_id.replace("-", "")}
    try:
        candidates.add(str(uuid.UUID(staff_id)))
    except ValueError:
        pass
    return candidates


def _fetch_recent_rows(staff_id: str, limit: int) -> list[RecentPatientInteraction]:
    return list(
        RecentPatientInteraction.objects.filter(
            staff_id__in=_staff_id_candidates(staff_id)
        )
        .order_by("-occurred_at")[:limit]
    )


def _hydrate_patients(patient_ids: list[str]) -> dict[str, Any]:
    if not patient_ids:
        return {}
    patients = Patient.objects.filter(id__in=patient_ids).only(
        "id", "first_name", "last_name", "birth_date"
    )
    return {str(p.id): p for p in patients}


def _format_dob(birth_date: Any) -> str | None:
    """Format a patient DOB as `M/D/YYYY` server-side.

    Important: don't return ISO `YYYY-MM-DD`. JavaScript's
    `new Date("YYYY-MM-DD")` parses date-only strings as UTC midnight
    (per ECMA-262), and `toLocaleDateString()` then renders in local
    time, shifting the date back one day for any user west of UTC
    (i.e. all U.S. timezones). Pre-formatting server-side bypasses
    the JS Date constructor entirely.
    """
    if birth_date is None:
        return None
    if isinstance(birth_date, str):
        return birth_date
    if isinstance(birth_date, date):
        return f"{birth_date.month}/{birth_date.day}/{birth_date.year}"
    return None


def _serialize_row(
    interaction: RecentPatientInteraction,
    patient: Any | None,
) -> dict[str, Any]:
    if patient is None:
        name = "(unknown patient)"
        dob = None
    else:
        first = (patient.first_name or "").strip()
        last = (patient.last_name or "").strip()
        name = f"{first} {last}".strip() or "(no name)"
        dob = _format_dob(patient.birth_date)
    return {
        "patient_id": interaction.patient_id,
        "name": name,
        "dob": dob,
        "interaction_type": interaction.interaction_type,
        "occurred_at": interaction.occurred_at.isoformat(),
    }


class RecentPatientsAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the recent-patients browse UI and JSON data.

    StaffSessionAuthMixin rejects patient sessions at the auth layer. Each
    response is scoped to the logged-in staff member via the
    `canvas-logged-in-user-id` header.
    """

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/data")
    def data(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        interactions = _fetch_recent_rows(staff_id, ROW_LIMIT)
        patient_map = _hydrate_patients([row.patient_id for row in interactions])
        rows = [
            _serialize_row(row, patient_map.get(row.patient_id)) for row in interactions
        ]
        return [
            JSONResponse(
                {
                    "rows": rows,
                    "server_time": datetime.now(UTC).isoformat(),
                }
            )
        ]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
