from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.note import NoteStateChangeEvent
from logger import log

from recent_patients.models.recent_patient_interaction import RecentPatientInteraction

CHART_VIEW = "chart_view"
PROFILE_VIEW = "profile_view"

LOCKED_STATE = "LKD"
CHART_REVIEW_CATEGORY = "review"


def _record(staff_id: str | None, patient_id: str | None, interaction_type: str) -> None:
    """Upsert one row per (staff, patient) with the latest touch."""
    if not staff_id or not patient_id:
        return
    RecentPatientInteraction.objects.update_or_create(
        staff_id=staff_id,
        patient_id=patient_id,
        defaults={
            "interaction_type": interaction_type,
            "occurred_at": datetime.now(UTC),
        },
    )


def _staff_uuid_from_canvas_user(user: Any) -> str | None:
    """A CanvasUser may resolve to either a Staff or a Patient. Only return Staff UUIDs."""
    if user is None:
        return None
    person = getattr(user, "person_subclass", None) or getattr(user, "staff", None)
    if person is None:
        return None
    if person.__class__.__name__ != "Staff":
        return None
    return str(getattr(person, "id", "")) or None


class _PatientLoadHandler(BaseHandler):
    """Shared base for chart-load and profile-load tracking.

    Both `PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION` and
    `PATIENT_PROFILE__SECTION_CONFIGURATION` fire with the patient id as
    `event.target.id` and the viewing staff member on `event.actor`. Same
    extraction, different `INTERACTION_TYPE`.
    """

    INTERACTION_TYPE: str = ""  # set by subclass

    def compute(self) -> list[Effect]:
        actor = self.event.actor
        if actor is None:
            return []

        canvas_user = getattr(actor, "instance", None)
        staff_id = _staff_uuid_from_canvas_user(canvas_user) if canvas_user else None
        patient_id = self.event.target.id

        _record(staff_id, patient_id, self.INTERACTION_TYPE)
        return []


class TrackChartView(_PatientLoadHandler):
    """Capture when a staff member opens a patient's chart."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)
    INTERACTION_TYPE = CHART_VIEW


class TrackProfileView(_PatientLoadHandler):
    """Capture when a staff member opens a patient's profile."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PROFILE__SECTION_CONFIGURATION)
    INTERACTION_TYPE = PROFILE_VIEW


class TrackChartReviewSign(BaseHandler):
    """Capture chart-review note sign-offs as a chart touch.

    This is the inbox/schedule result-review path: a staff member signs
    off on a lab, image, consult, or uncategorized document from the
    schedule view. Canvas creates a chart-review category note and locks
    it. The chart itself never loads, so
    PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION doesn't fire — this
    handler is the safety net.

    Recorded as `chart_view` (same kind as opening the chart directly)
    because the plugin no longer distinguishes view vs action.
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        if self.event.context.get("state") != LOCKED_STATE:
            return []

        nsce_id = self.event.target.id
        try:
            nsce = NoteStateChangeEvent.objects.select_related(
                "note__note_type_version", "note__patient", "originator"
            ).get(id=nsce_id)
        except NoteStateChangeEvent.DoesNotExist:
            log.warning("NoteStateChangeEvent %s not found", nsce_id)
            return []

        category = (
            nsce.note.note_type_version.category
            if nsce.note and nsce.note.note_type_version
            else None
        )
        if category != CHART_REVIEW_CATEGORY:
            return []

        staff_id = _staff_uuid_from_canvas_user(nsce.originator)
        patient_id = self.event.context.get("patient_id") or (
            str(nsce.note.patient.id) if nsce.note and nsce.note.patient else None
        )
        _record(staff_id, patient_id, CHART_VIEW)
        return []
