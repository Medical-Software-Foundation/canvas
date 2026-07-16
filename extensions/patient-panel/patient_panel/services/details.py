"""Accordion detail fetchers (tasks, comments, gaps, conditions, medications,
allergies, referrals) for a single patient.

Pure ORM readers. Date-formatting ones take a `format_local` callable (the
API's tz-bound formatter) so timezone resolution stays on the class.
"""

import re
from typing import Any, Callable

from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.protocol_current import ProtocolCurrent
from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus
from canvas_sdk.v1.data.referral import Referral
from canvas_sdk.v1.data.task import Task, TaskComment, TaskStatus


def clean_task_title(title: str | None) -> str | None:
    """Clean Canvas markup from task titles.

    Returns the title with Canvas markup replaced by the display name portion.
    Returns None unchanged when None is passed (task.title may be None in the
    ORM), and returns an empty string unchanged for empty input.
    """
    if not title:
        return title
    pattern = r"<[^:]+:[^:]+:[^|]+\|([^>]+)>"
    return re.sub(pattern, r"\1", title)


def get_open_tasks(patient_id: str) -> list[dict[str, Any]]:
    """Get open tasks with their comment counts for a patient."""
    tasks = (
        Task.objects.filter(patient__id=patient_id, status=TaskStatus.OPEN)
        .select_related("assignee")
        .prefetch_related("comments")
        .order_by("-created")
    )
    return [
        {
            "id": task.id,
            "title": clean_task_title(task.title),
            "due": task.due,
            "assignee": (
                task.assignee.credentialed_name if task.assignee else "Unassigned"
            ),
            "comments_count": len(task.comments.all()),
        }
        for task in tasks
    ]


def get_task_comments(task_id: str, *, format_local: Callable[[Any, str], str]) -> list[dict]:
    """Get comments for a specific task."""
    comments = (
        TaskComment.objects.filter(task__id=task_id)
        .select_related("creator")
        .order_by("created")
    )
    return [
        {
            "creator": {
                "first_name": comment.creator.first_name,
                "last_name": comment.creator.last_name,
                "name": (
                    comment.creator.credentialed_name
                    if comment.creator
                    else "Unknown"
                ),
            },
            "content": comment.body,
            "date": format_local(comment.created, "MM.DD.YYYY HH:mm"),
        }
        for comment in comments
    ]


def get_gaps_details(patient_id: str) -> Any:
    """Get detailed gaps in care for a patient (due only)."""
    return ProtocolCurrent.objects.filter(
        patient__id=patient_id,
        status=ProtocolResultStatus.STATUS_DUE,
    ).values("id", "title", "status")


def get_conditions_details(
    patient_id: str, *, format_local: Callable[[Any, str], str]
) -> list[dict[str, Any]]:
    """Get active conditions for the accordion view.

    Collapses multiple codings per condition into a single row — picks a
    display-bearing coding for the name and an ICD-10 coding (when present)
    for the code.
    """
    conditions = (
        Condition.objects.for_patient(patient_id)
        .active()
        .prefetch_related("codings")
        .order_by("-onset_date")
    )
    result = []
    for condition in conditions:
        codings = list(condition.codings.all())
        display_coding = next((c for c in codings if c.display), None)
        icd_coding = next(
            (c for c in codings if c.system and "icd" in c.system.lower()),
            None,
        )
        result.append({
            "id": str(condition.id),
            "display": (
                display_coding.display if display_coding else "(no description)"
            ),
            "code": (
                icd_coding.code if icd_coding else
                (display_coding.code if display_coding else "")
            ),
            "onset_date": (
                format_local(condition.onset_date, "MM.DD.YYYY")
                if condition.onset_date else ""
            ),
        })
    return result


def get_medications_details(
    patient_id: str, *, format_local: Callable[[Any, str], str]
) -> list[dict[str, Any]]:
    """Get active medications for the accordion view."""
    medications = (
        Medication.objects.for_patient(patient_id)
        .active()
        .prefetch_related("codings")
        .order_by("-start_date")
    )
    result = []
    for med in medications:
        codings = list(med.codings.all())
        display_coding = next((c for c in codings if c.display), None)
        result.append({
            "id": str(med.id),
            "display": (
                display_coding.display if display_coding
                else (med.clinical_quantity_description or "(no description)")
            ),
            "quantity": med.clinical_quantity_description or "",
            "start_date": (
                format_local(med.start_date, "MM.DD.YYYY")
                if med.start_date else ""
            ),
        })
    return result


def get_allergies_details(
    patient_id: str, *, format_local: Callable[[Any, str], str]
) -> list[dict[str, Any]]:
    """Get allergies for the accordion view."""
    allergies = (
        AllergyIntolerance.objects.filter(patient__id=patient_id, deleted=False)
        .prefetch_related("codings")
        .order_by("-recorded_date")
    )
    result = []
    for allergy in allergies:
        codings = list(allergy.codings.all())
        display_coding = next((c for c in codings if c.display), None)
        result.append({
            "id": str(allergy.id),
            "display": (
                display_coding.display if display_coding else "(no description)"
            ),
            "severity": allergy.severity or "",
            "recorded_date": (
                format_local(allergy.recorded_date, "MM.DD.YYYY")
                if allergy.recorded_date else ""
            ),
        })
    return result


def get_referrals_details(
    patient_id: str, *, format_local: Callable[[Any, str], str]
) -> list[dict[str, Any]]:
    """Get referrals for the accordion view."""
    referrals = (
        Referral.objects.filter(patient__id=patient_id, deleted=False)
        .select_related("service_provider")
        .order_by("-date_referred")
    )
    result = []
    for ref in referrals:
        provider = ref.service_provider
        provider_name = ""
        if provider:
            first = getattr(provider, "first_name", "") or ""
            last = getattr(provider, "last_name", "") or ""
            provider_name = f"{first} {last}".strip()
        result.append({
            "id": str(ref.id),
            "clinical_question": ref.clinical_question or "(no clinical question)",
            "provider": provider_name,
            "priority": ref.priority or "",
            "date_referred": (
                format_local(ref.date_referred, "MM.DD.YYYY")
                if ref.date_referred else ""
            ),
        })
    return result
