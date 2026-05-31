"""`prep_visit_panel` chat tool: pre-visit prep digest for a clinician's panel."""

from datetime import date as _date
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.lab import LabValue
from canvas_sdk.v1.data.medication_statement import MedicationStatement
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import Task


class PrepVisitPanelArgs(BaseModel):
    """Arguments for the `prep_visit_panel` chat tool."""

    model_config = ConfigDict(extra="forbid")

    date: _date | None = Field(None, description="ISO date YYYY-MM-DD. Defaults to today.")
    provider_id: str | None = Field(
        None,
        description=(
            "Staff id of the provider whose panel to prep. "
            "Defaults to the requesting staff_id when omitted."
        ),
    )
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max appointments to digest (default 20, max {MAX_RESULT_LIMIT}).",
    )


def prep_visit_panel(instance: Any, args: PrepVisitPanelArgs) -> dict:
    """Handler for the `prep_visit_panel` chat tool.

    Bundles per-appointment prep signals (conditions, meds, recent
    abnormal labs, open tasks, last visit) into one tool call so the
    common "prep tomorrow" workflow fits inside the loop budget — 1 call
    instead of 4× per patient.
    """
    target_date = args.date or _date.today()

    provider_id = args.provider_id or getattr(instance, "_requesting_staff_id", None)
    if not provider_id:
        return {
            "error": (
                "provider_id required (no staff_id in context); "
                "pass provider_id explicitly or call with a logged-in staff context"
            )
        }

    provider = (
        Staff.objects.filter(id=provider_id).values("first_name", "last_name").first()
    )
    provider_name = (
        " ".join(filter(None, [provider["first_name"], provider["last_name"]])).strip()
        or None
        if provider
        else None
    )

    appts = list(
        Appointment.objects.filter(
            provider__id=provider_id,
            start_time__date=target_date,
        )
        .exclude(status__in=["cancelled", "noshowed"])
        .order_by("start_time")
        .values(
            "id",
            "start_time",
            "duration_minutes",
            "status",
            "patient__id",
            "patient__first_name",
            "patient__last_name",
            "patient__birth_date",
            "patient__sex_at_birth",
        )[: args.limit]
    )

    per_patient_limit = 5
    lab_floor = target_date - timedelta(days=90)
    patients_out: list[dict] = []

    for a in appts:
        pid = a["patient__id"]
        patient_name = (
            " ".join(filter(None, [a["patient__first_name"], a["patient__last_name"]])).strip()
            or None
        )
        birth = a["patient__birth_date"]
        age = None
        if birth:
            age = (
                target_date.year
                - birth.year
                - ((target_date.month, target_date.day) < (birth.month, birth.day))
            )

        conditions: list[dict] = []
        for cond in (
            Condition.objects.committed().filter(
                patient__id=pid, resolution_date__isnull=True
            )
            .prefetch_related("codings")
            .order_by("-onset_date")[:per_patient_limit]
        ):
            name = next(
                ((c.display or "").strip() for c in cond.codings.all() if c.display), None
            )
            conditions.append(
                {
                    "name": name,
                    "onset_date": cond.onset_date.isoformat() if cond.onset_date else None,
                }
            )

        meds: list[dict] = []
        med_qs = (
            MedicationStatement.objects.filter(
                patient__id=pid,
                end_date__isnull=True,
                deleted=False,
                entered_in_error__isnull=True,
            )
            .select_related("medication")
            .prefetch_related("medication__codings")
            .order_by("-start_date")[:per_patient_limit]
        )
        for ms in med_qs:
            name = None
            if ms.medication is not None:
                name = next(
                    (
                        (c.display or "").strip()
                        for c in ms.medication.codings.all()
                        if c.display
                    ),
                    None,
                )
            meds.append({"name": name, "sig": ms.sig_original_input or None})

        labs: list[dict] = []
        for r in (
            LabValue.objects.filter(
                report__patient__id=pid,
                report__junked=False,
                report__entered_in_error__isnull=True,
                report__original_date__date__gte=lab_floor,
            )
            .exclude(abnormal_flag="")
            .order_by("-report__original_date")
            .values(
                "value",
                "units",
                "abnormal_flag",
                "test__ontology_test_name",
                "report__original_date",
            )[:per_patient_limit]
        ):
            labs.append(
                {
                    "test_name": r["test__ontology_test_name"] or None,
                    "value": r["value"] or None,
                    "units": r["units"] or None,
                    "abnormal_flag": r["abnormal_flag"] or None,
                    "date": r["report__original_date"].isoformat()
                    if r["report__original_date"]
                    else None,
                }
            )

        tasks_out: list[dict] = []
        for t in (
            Task.objects.filter(patient__id=pid, status="OPEN")
            .order_by("due", "-created")
            .values("id", "title", "due")[:per_patient_limit]
        ):
            tasks_out.append(
                {
                    "task_id": t["id"],
                    "title": t["title"],
                    "due": t["due"].isoformat() if t["due"] else None,
                }
            )

        last_visit = (
            Note.objects.filter(patient__id=pid, datetime_of_service__date__lt=target_date)
            .order_by("-datetime_of_service")
            .values("datetime_of_service", "note_type")
            .first()
        )

        patients_out.append(
            {
                "patient_id": pid,
                "patient_name": patient_name,
                "age": age,
                "sex_at_birth": a["patient__sex_at_birth"],
                "appointment_id": a["id"],
                "appointment_start_time": a["start_time"].isoformat()
                if a["start_time"]
                else None,
                "appointment_duration_minutes": a["duration_minutes"],
                "appointment_status": a["status"],
                "active_conditions": conditions,
                "active_medications": meds,
                "recent_abnormal_labs": labs,
                "open_tasks": tasks_out,
                "last_visit_date": (
                    last_visit["datetime_of_service"].isoformat()
                    if last_visit and last_visit["datetime_of_service"]
                    else None
                ),
                "last_visit_type": last_visit["note_type"] if last_visit else None,
            }
        )

    return {
        "date": target_date.isoformat(),
        "provider_id": provider_id,
        "provider_name": provider_name,
        "panel_size": len(patients_out),
        "patients": patients_out,
    }

TOOL_SPEC = {
    "name": "prep_visit_panel",
    "description": "Pre-visit prep digest for a clinician's panel on a given date. "
    "For each scheduled appointment that day, returns one compact "
    "bundle: appointment time/status, patient demographics, active "
    "conditions (unresolved), current medications (no end_date), "
    "recent abnormal labs (last 90 days), open tasks linked to the "
    "patient, and the date/type of the prior visit. Use this for "
    "'prep tomorrow', 'morning rounds', 'who am I seeing today' — "
    "one call instead of 4× per patient. Defaults: date = today, "
    "provider_id = the requesting staff_id.",
    "args_model": PrepVisitPanelArgs,
    "handler": prep_visit_panel,
    "mutates": False,
}
