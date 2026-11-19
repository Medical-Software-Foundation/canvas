from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.staff import Staff

from supervisor_cosign.models.cosign_record import CoSignRecord


def note_uuid_for_dbid(note_dbid: str | int | None) -> str | None:
    """The note UUID for a note dbid (what button events carry as note_id), or None."""
    if note_dbid is None or note_dbid == "":
        return None
    note_uuid = Note.objects.filter(dbid=note_dbid).values_list("id", flat=True).first()
    return str(note_uuid) if note_uuid else None


def staff_id_for_user(user_dbid: str | None) -> str | None:
    """The Staff id behind a CanvasUser dbid (an event's actor id), or None."""
    if not user_dbid:
        return None
    staff_id = Staff.objects.filter(user__dbid=user_dbid).values_list("id", flat=True).first()
    return str(staff_id) if staff_id else None


# Co-sign unlocks, attests, and re-signs, so it only applies to a closed note. An
# unlocked note with a pending record keeps the native footer so it can be closed.
COSIGNABLE_STATES = (NoteStates.LOCKED, NoteStates.SIGNED)


def viewer_owes_cosign(note_uuid: str | None, user_dbid: str | None) -> bool:
    """Whether the viewing user is the supervisor on a pending co-sign record for a locked or signed note."""
    if not note_uuid:
        return False
    staff_id = staff_id_for_user(user_dbid)
    if not staff_id:
        return False
    if not CoSignRecord.objects.filter(
        note_id=note_uuid, supervisor_id=staff_id, status="pending"
    ).exists():
        return False
    return CurrentNoteStateEvent.objects.filter(
        note__id=note_uuid, state__in=COSIGNABLE_STATES
    ).exists()
