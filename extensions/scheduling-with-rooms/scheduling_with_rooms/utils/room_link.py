"""Link a patient appointment to the room it holds, via note metadata.

The obvious link — ``Appointment.parent_appointment_id`` on the room
``ScheduleEvent`` — does not survive a reschedule. ``ScheduleEvent.reschedule()``
mints a new row with ``parent_appointment_id`` set to NULL, so after one
reschedule the room event is orphaned and the plugin can no longer find it.
Observed on bigleaphealth-dev: room event 1160 (parent=1159) rescheduled to
1162 (parent=NULL).

The note is the one identifier that *is* stable. A reschedule chain keeps the
same note while the appointment id changes at every step (1159 → 1161 → 1163
all carried note 3863), so the room a visit holds is recorded as note metadata.

Only the room's staff key is stored, not the ScheduleEvent id: effects don't
return the ids of records they create, so the plugin never learns the event's
id. The key narrows the search from "any of this visit type's allowed rooms" to
exactly one, and the event is then located by
``(patient, that room, start_time, schedule_event)``.

https://docs.canvasmedical.com/sdk/effect-note-metadata/
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteMetadata, NoteTypeCategories
from logger import log

# Namespaced so it can't collide with another plugin's metadata.
ROOM_STAFF_KEY = "scheduling_with_rooms:room_staff_key"


def record_room(note_id: str, room_staff_key: str) -> list[Effect]:
    """Return the effect recording which room a visit's note holds.

    Returns an empty list when either argument is missing, so callers can
    unconditionally extend their effect list.
    """
    if not note_id or not room_staff_key:
        return []
    log.info("room-link: recording room %s on note %s", room_staff_key, note_id)
    return [Note(instance_id=note_id).upsert_metadata(ROOM_STAFF_KEY, room_staff_key)]


def room_staff_key_for_note(note_id: str) -> str:
    """Return the room staff key recorded on a note, or ``""``.

    Empty means the visit has no room on record — either it never had one, or
    it was booked before this metadata was written.
    """
    if not note_id:
        return ""
    row = (
        NoteMetadata.objects.filter(note__id=note_id, key=ROOM_STAFF_KEY)
        .values("value")
        .first()
    )
    return str(row["value"]).strip() if row and row["value"] else ""


def find_room_events(appointment: Appointment) -> list:
    """Return the live room ScheduleEvent(s) an appointment holds.

    Two lookups, in order:

    1. ``children`` — the ``parent_appointment_id`` link ``/book`` sets at
       create. Exact, and correct for an appointment never rescheduled.
    2. The room recorded on the note, matched against the appointment's current
       time. Needed because ``ScheduleEvent.reschedule()`` nulls
       ``parent_appointment_id`` and the SDK refuses to set it outside a create
       ("parent_appointment_id can only be set when creating an appointment"),
       so from the first reschedule onward ``children`` is permanently empty.

    Shared by the reschedule path and the cancellation cascade so the two can't
    disagree about which room a visit holds.
    """
    live = [
        child
        for child in appointment.children.all()
        if child.note_type
        and child.note_type.category == NoteTypeCategories.SCHEDULE_EVENT
        and child.status != AppointmentProgressStatus.CANCELLED
    ]
    if live:
        return live

    note_id = str(appointment.note.id) if appointment.note else ""
    room_staff_key = room_staff_key_for_note(note_id)
    if not room_staff_key or not appointment.patient:
        return []

    recovered = list(
        Appointment.objects.filter(
            patient__id=str(appointment.patient.id),
            provider__id=room_staff_key,
            start_time=appointment.start_time,
            note_type__category=NoteTypeCategories.SCHEDULE_EVENT,
        ).exclude(status=AppointmentProgressStatus.CANCELLED)
    )
    if recovered:
        log.info(
            "room-link: recovered %d room event(s) for appointment %s via note %s "
            "(room=%s); parent_appointment_id was not usable",
            len(recovered), appointment.id, note_id, room_staff_key,
        )
    return recovered


__all__ = (
    "ROOM_STAFF_KEY",
    "find_room_events",
    "record_room",
    "room_staff_key_for_note",
)
