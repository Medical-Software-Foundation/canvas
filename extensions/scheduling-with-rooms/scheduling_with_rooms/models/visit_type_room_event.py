"""Per-visit-type "room is booked" NoteType code.

When a visit type is mapped to one or more rooms (see
``VisitTypeRoomMapping``), the booking flow creates a ``ScheduleEvent`` on
the chosen room's calendar. Different visit types may use different
``schedule_event`` NoteTypes — this model holds the chosen code per visit
type. Effectively a singleton-per-visit-type config table.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField


class VisitTypeRoomEvent(CustomModel):
    note_type_code = CharField(max_length=128)
    room_event_note_type_code = CharField(max_length=128, default="")


def get_room_event_code_for(note_type_code: str) -> str:
    """Return the configured ScheduleEvent NoteType code for a visit type, or ''."""
    if not note_type_code:
        return ""
    obj = (
        VisitTypeRoomEvent.objects
        .filter(note_type_code=note_type_code)
        .values_list("room_event_note_type_code", flat=True)
        .first()
    )
    return obj or ""


def replace_room_event_codes(by_note_type: dict[str, str]) -> None:
    """Replace-all save: for each (note_type_code, room_event_code) pair, upsert.

    Empty room_event_code clears the row for that visit type.
    """
    if not by_note_type:
        return
    codes = list(by_note_type.keys())
    VisitTypeRoomEvent.objects.filter(note_type_code__in=codes).delete()
    rows: list[VisitTypeRoomEvent] = []
    for code, event_code in by_note_type.items():
        if isinstance(code, str) and code and isinstance(event_code, str) and event_code:
            rows.append(VisitTypeRoomEvent(
                note_type_code=code,
                room_event_note_type_code=event_code,
            ))
    if rows:
        VisitTypeRoomEvent.objects.bulk_create(rows)
