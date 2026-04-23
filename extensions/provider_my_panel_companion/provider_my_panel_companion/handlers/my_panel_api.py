from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from django.db.models import Count, Max, Min

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.task import Task, TaskStatus

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


def _fetch_panel_patients(staff_uuid: str) -> list:
    """Active patients whose care team includes the given staff member."""
    memberships = (
        CareTeamMembership.objects.filter(
            staff__id=staff_uuid,
            status=CareTeamMembershipStatus.ACTIVE,
        )
        .select_related("patient")
        .order_by("patient__last_name", "patient__first_name")
    )
    seen: set[str] = set()
    patients: list = []
    for membership in memberships:
        patient = membership.patient
        if patient is None:
            continue
        uuid = str(patient.id)
        if uuid in seen:
            continue
        seen.add(uuid)
        patients.append(patient)
    return patients


def _last_appointment_by_patient(patient_uuids: list[str], now: datetime) -> dict:
    """Most recent appointment `start_time` strictly before `now`, keyed by patient UUID."""
    if not patient_uuids:
        return {}
    rows = (
        Appointment.objects.filter(
            patient__id__in=patient_uuids,
            start_time__lt=now,
        )
        .values("patient__id")
        .annotate(last=Max("start_time"))
    )
    return {str(row["patient__id"]): row["last"] for row in rows}


def _next_appointment_by_patient(patient_uuids: list[str], now: datetime) -> dict:
    """Earliest appointment `start_time` at or after `now`, keyed by patient UUID."""
    if not patient_uuids:
        return {}
    rows = (
        Appointment.objects.filter(
            patient__id__in=patient_uuids,
            start_time__gte=now,
        )
        .values("patient__id")
        .annotate(next=Min("start_time"))
    )
    return {str(row["patient__id"]): row["next"] for row in rows}


def _open_task_count_by_patient(patient_uuids: list[str]) -> dict:
    """Count of OPEN tasks per patient, keyed by patient UUID."""
    if not patient_uuids:
        return {}
    rows = (
        Task.objects.filter(
            patient__id__in=patient_uuids,
            status=TaskStatus.OPEN,
        )
        .values("patient__id")
        .annotate(count=Count("id"))
    )
    return {str(row["patient__id"]): row["count"] for row in rows}


def _serialize_patient(
    patient: Any,
    last_appointment: datetime | None,
    next_appointment: datetime | None,
    open_task_count: int,
) -> dict:
    return {
        "id": str(patient.id),
        "name": f"{patient.first_name} {patient.last_name}".strip(),
        "last_appointment": last_appointment.isoformat() if last_appointment else None,
        "next_appointment": next_appointment.isoformat() if next_appointment else None,
        "open_task_count": open_task_count,
    }


class MyPanelAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the My Panel companion UI and JSON data."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/patients")
    def patients(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers["canvas-logged-in-user-id"]

        panel = _fetch_panel_patients(staff_uuid)
        patient_uuids = [str(patient.id) for patient in panel]

        now = datetime.now(timezone.utc)
        last_by_patient = _last_appointment_by_patient(patient_uuids, now)
        next_by_patient = _next_appointment_by_patient(patient_uuids, now)
        task_counts_by_patient = _open_task_count_by_patient(patient_uuids)

        serialized = [
            _serialize_patient(
                patient,
                last_by_patient.get(str(patient.id)),
                next_by_patient.get(str(patient.id)),
                task_counts_by_patient.get(str(patient.id), 0),
            )
            for patient in panel
        ]

        return [JSONResponse({"patients": serialized})]

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
