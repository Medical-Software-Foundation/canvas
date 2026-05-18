from __future__ import annotations

from datetime import UTC, datetime
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


def _fetch_recent_rows(staff_id: str, limit: int) -> list[RecentPatientInteraction]:
    return list(
        RecentPatientInteraction.objects.filter(staff_id=staff_id)
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
    if birth_date is None:
        return None
    if isinstance(birth_date, str):
        return birth_date
    try:
        result: str = birth_date.isoformat()
        return result
    except AttributeError:
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
