"""Translate a scheduling-form payload into Canvas SDK appointment effects.

Kept separate from the SimpleAPI handler so the effect-building logic is unit
testable without an HTTP request.

Payload shape (from the iframe UI's POST /app/book)::

    {
      "mode": "schedule" | "reschedule",
      "category": "appointment" | "schedule_event",
      "patient_id": "<patient key>",          # required for appointment
      "appointment_id": "<external id>",       # reschedule only
      "note_id": "<note external id>",         # reschedule only, server-injected
      "rfv_command_id": "<command uuid>",      # reschedule only, server-injected
      "grouping": "concurrent" | "sequential", # multi-visit only
      "visits": [
        {
          "providers": ["<staff key>", ...],   # <= 3
          "location_id": "<external id>",
          "visit_type_id": "<note type id>",
          "duration_minutes": 30,
          "start_time": "2026-06-10T09:00:00",  # ISO 8601 (manual entry)
          "labels": ["Follow up", ...],         # <= 3, appointment only
          "description": "...",                 # schedule_event custom title
          "meeting_link": "...",                # optional telehealth
          "reason_for_visit": "...",            # free-text RFV (appointment only)
          "reason_for_visit_coding": "<id>",    # coded RFV external id (structured)
          "reason_for_visit_comment": "..."     # optional comment for a coded RFV
        }
      ],
      "recurrence": {                            # optional, appointment only
        "frequency": "daily" | "weekly" | "monthly",
        "interval": 1,                           # every N
        "count": 4                               # total incl. parent — OR —
        # "until": "2026-09-01"                  # inclusive end date
      }
    }
"""

import datetime
import json
from typing import Any
from uuid import uuid4

from canvas_sdk.commands import ReasonForVisitCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import AppointmentIdentifier
from canvas_sdk.effects.note.appointment import Appointment, ScheduleEvent
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from scheduling_app.recurrence import RECURRENCE_SYSTEM, RFV_SYSTEM, encode_recurrence, encode_rfv


def _parse_start(value: str) -> datetime.datetime:
    """Parse an ISO-8601 datetime string from the form."""
    return datetime.datetime.fromisoformat(value)


def _labels(visit: dict[str, Any]) -> set[str] | None:
    """Return the visit's labels as a set (the effect rejects an empty set)."""
    labels = [label for label in visit.get("labels", []) if label]
    return set(labels) or None


def _appointment_effect(
    payload: dict[str, Any],
    visit: dict[str, Any],
    provider_id: str,
    start: datetime.datetime,
    instance_id: str,
    recurrence: dict[str, Any] | None = None,
) -> Effect:
    """Build a CREATE_APPOINTMENT effect for one provider of a patient visit.

    ``instance_id`` becomes the created note's ``externally_exposable_id``, so a
    follow-up ReasonForVisit command can target the note by that id. When
    ``recurrence`` is given, the rule is stamped onto the appointment as a
    plugin-namespaced external identifier; the APPOINTMENT_CREATED handler
    (handlers/recurrence.py) reads it back to create the linked series.
    """
    # Only set external_identifiers when recurring: the home-app interpreter
    # iterates the payload value, so a None would serialize to null and blow up
    # CREATE_APPOINTMENT for every non-recurring booking.
    extra: dict[str, Any] = {}
    if recurrence:
        identifiers = [
            AppointmentIdentifier(system=RECURRENCE_SYSTEM, value=encode_recurrence(recurrence))
        ]
        # Carry the reason for visit too, so the APPOINTMENT_CREATED handler can
        # replicate it onto each child without racing the parent's note RFV
        # command (which is a separate, async effect).
        if rfv_value := encode_rfv(visit):
            identifiers.append(AppointmentIdentifier(system=RFV_SYSTEM, value=rfv_value))
        extra["external_identifiers"] = identifiers
    return Appointment(
        instance_id=instance_id,
        appointment_note_type_id=visit["visit_type_id"],
        patient_id=payload["patient_id"],
        provider_id=provider_id,
        practice_location_id=visit["location_id"],
        start_time=start,
        duration_minutes=int(visit["duration_minutes"]),
        status=AppointmentProgressStatus.UNCONFIRMED,
        labels=_labels(visit),
        meeting_link=visit.get("meeting_link") or None,
        **extra,
    ).create()


def _rfv_command(
    visit: dict[str, Any], *, note_uuid: str | None = None, command_uuid: str | None = None
) -> ReasonForVisitCommand | None:
    """Build the reason-for-visit command for a visit, or None when nothing to record.

    Free-text RFV is stored as the command's comment; a coded RFV is sent as
    ``structured`` with the coding's external id (plus an optional comment). The
    target is set at construction: ``note_uuid`` for an originate, ``command_uuid``
    for an edit.
    """
    reason = (visit.get("reason_for_visit") or "").strip()
    coding = visit.get("reason_for_visit_coding") or None
    comment = (visit.get("reason_for_visit_comment") or "").strip() or None
    if not reason and not coding:
        return None
    target: dict[str, str] = {}
    if note_uuid:
        target["note_uuid"] = note_uuid
    if command_uuid:
        target["command_uuid"] = command_uuid
    if coding:
        return ReasonForVisitCommand(structured=True, coding=coding, comment=comment, **target)
    return ReasonForVisitCommand(comment=reason, **target)


def _rfv_effect(note_uuid: str, visit: dict[str, Any]) -> Effect | None:
    """ORIGINATE a reason-for-visit command on the appointment's note, if any.

    The note is created by the CREATE_APPOINTMENT effect with
    ``externally_exposable_id == note_uuid`` (the appointment's instance_id), so
    the command targets it by that id. Returns None when there's no reason.
    """
    command = _rfv_command(visit, note_uuid=note_uuid)
    return command.originate() if command else None


def _reschedule_rfv_effect(
    visit: dict[str, Any], note_uuid: str | None, command_uuid: str | None
) -> Effect | None:
    """Edit, originate, or clear the note's reason-for-visit on reschedule.

    A reschedule reuses the same note, so an existing RFV command can be edited in
    place by its uuid; if none exists yet, originate one on the note; if the user
    cleared the reason, retire the existing command. ``note_uuid`` and
    ``command_uuid`` are resolved server-side (see scheduling_web_app.py), so this
    stays a pure payload-to-effect function.
    """
    if command_uuid:
        if command := _rfv_command(visit, command_uuid=command_uuid):
            return command.edit()
        # The reason was cleared: retire the existing command.
        return ReasonForVisitCommand(command_uuid=command_uuid).enter_in_error()
    if note_uuid:
        command = _rfv_command(visit, note_uuid=note_uuid)
        return command.originate() if command else None
    return None


def _schedule_event_effect(
    payload: dict[str, Any], visit: dict[str, Any], provider_id: str, start: datetime.datetime
) -> Effect:
    """Build a CREATE_SCHEDULE_EVENT effect for one provider of an 'Other Event'."""
    return ScheduleEvent(
        note_type_id=visit["visit_type_id"],
        patient_id=payload.get("patient_id") or None,
        description=visit.get("description") or None,
        provider_id=provider_id,
        practice_location_id=visit["location_id"],
        start_time=start,
        duration_minutes=int(visit["duration_minutes"]),
        status=AppointmentProgressStatus.UNCONFIRMED,
    ).create()


def _reschedule_effect(payload: dict[str, Any]) -> list[Effect]:
    """Build a RESCHEDULE_APPOINTMENT effect (+ a reason-for-visit edit, if any).

    Labels are injected into the payload rather than set on the effect: the SDK
    validates reschedule labels *additively* (existing + new <= 3), wrongly
    counting the OLD appointment's labels even though home-app replaces them on a
    fresh new appointment — so editing labels would spuriously hit the 3-label
    limit. Building the effect without labels skips that check; home-app reads the
    injected ``labels`` and applies them as the new appointment's set. (An empty
    set is omitted, so home-app copies the original's labels — unchanged.)
    ``note_id`` and ``rfv_command_id`` are injected server-side by the /book handler.
    """
    visit = payload["visits"][0]
    provider = (visit.get("providers") or [None])[0]
    reschedule = Appointment(
        instance_id=payload["appointment_id"],
        provider_id=provider,
        practice_location_id=visit["location_id"],
        start_time=_parse_start(visit["start_time"]),
        duration_minutes=int(visit["duration_minutes"]),
    ).reschedule()
    if labels := _labels(visit):
        data = json.loads(reschedule.payload)
        data["data"]["labels"] = sorted(labels)
        reschedule = Effect(type=reschedule.type, payload=json.dumps(data))
    effects: list[Effect] = [reschedule]
    if rfv := _reschedule_rfv_effect(visit, payload.get("note_id"), payload.get("rfv_command_id")):
        effects.append(rfv)
    return effects


def build_booking_effects(payload: dict[str, Any]) -> list[Effect]:
    """Build the appointment effect(s) for a scheduling-form submission.

    - Reschedule: one RESCHEDULE_APPOINTMENT for the (single) appointment, plus a
      reason-for-visit edit/originate/clear when the form's reason changed (labels
      are read-only — home-app carries them over automatically).
    - Schedule: one CREATE per provider per visit. Sequential visits chain
      (each starts when the previous ends); concurrent visits keep their own
      start time. Note: v1 books independent appointments — they are not linked
      as a single scheduled-together group (see README).
    - Recurrence (appointments only): when ``payload["recurrence"]`` is set, each
      created appointment is stamped with the rule and becomes a series parent;
      the APPOINTMENT_CREATED handler then creates the linked child occurrences.
    """
    if payload.get("mode") == "reschedule":
        return _reschedule_effect(payload)

    is_schedule_event = payload.get("category") == "schedule_event"
    grouping = payload.get("grouping", "concurrent")
    # Recurrence applies to appointments only (not schedule events).
    recurrence = None if is_schedule_event else payload.get("recurrence")

    effects: list[Effect] = []
    sequential_cursor: datetime.datetime | None = None
    for visit in payload["visits"]:
        if grouping == "sequential" and sequential_cursor is not None:
            start = sequential_cursor
        else:
            start = _parse_start(visit["start_time"])

        for provider_id in visit["providers"]:
            if is_schedule_event:
                effects.append(_schedule_event_effect(payload, visit, provider_id, start))
            else:
                # Each provider gets its own appointment + note; key them by a
                # known id so the RFV command can target the note (appointments
                # only — reason-for-visit doesn't apply to schedule events).
                instance_id = str(uuid4())
                effects.append(
                    _appointment_effect(payload, visit, provider_id, start, instance_id, recurrence)
                )
                if rfv := _rfv_effect(instance_id, visit):
                    effects.append(rfv)

        sequential_cursor = start + datetime.timedelta(minutes=int(visit["duration_minutes"]))

    return effects
