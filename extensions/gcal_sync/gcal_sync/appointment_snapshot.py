"""Build the non-PHI :class:`AppointmentSnapshot` the sync engine pushes to Google.

Shared by the push handler, the webhook (Canvas-wins re-push), and the reconciliation cron so the
exact same field selection and meeting-link resolution are used everywhere.

Covers BOTH calendar record kinds, which Canvas stores in the same ``Appointment`` table:
- **Appointments** (``note_type.category == "appointment"``/encounter): patient visits. Title is the
  visit type; the telehealth link goes in the description. Patient free-text is never read.
- **Schedule events** (``note_type.category == "schedule_event"``): admin holds/blocks with no
  patient. Title is the block's description/type; no meeting link.
"""

from canvas_sdk.v1.data.appointment import Appointment, AppointmentExternalIdentifier

from gcal_sync.google.event_builder import AppointmentSnapshot

# External-identifier system stamped on Canvas records we created FROM a Google event. Used to skip
# pushing them back (loop suppression) and to find them again for update/delete.
GOOGLE_ORIGIN_SYSTEM = "gcal-sync"


def resolve_meeting_link(appt: dict) -> str | None:
    """Effective meeting link for an appointment: the appointment's own link, else (for telehealth)
    the provider's standing personal room. In-person visits get none."""
    link = appt.get("meeting_link")
    if link:
        return str(link)
    if appt.get("note_type__is_telehealth"):
        room = appt.get("provider__personal_meeting_room_link")
        return str(room) if room else None
    return None

SCHEDULE_EVENT_CATEGORY = "schedule_event"

# Only non-PHI fields are selected — patient is omitted entirely; description is read only for
# schedule events (admin blocks, no patient), never for patient appointments.
APPOINTMENT_FIELDS = (
    "id",
    "provider__id",
    "note_type__display",
    "note_type__category",
    "note_type__is_telehealth",
    "start_time",
    "duration_minutes",
    "location__short_name",
    "status",
    "meeting_link",
    "description",
    "provider__personal_meeting_room_link",
)


def _is_schedule_event(appt: dict) -> bool:
    return appt.get("note_type__category") == SCHEDULE_EVENT_CATEGORY


def snapshot_from_values(appt: dict) -> AppointmentSnapshot:
    """Turn a ``.values(*APPOINTMENT_FIELDS)`` row into an :class:`AppointmentSnapshot`.

    For schedule events the title is the block description (or its type), and no meeting link is
    attached. For appointments the title is the visit type and the telehealth link is resolved.
    """
    if _is_schedule_event(appt):
        # Admin block: description is the provider-set block title (no patient), safe to use.
        title = appt.get("description") or appt.get("note_type__display") or "Busy"
        meeting_link = None
    else:
        title = appt.get("note_type__display")
        meeting_link = resolve_meeting_link(appt)

    return {
        "appointment_id": str(appt["id"]),
        "visit_type": title,
        "start_time": appt["start_time"],
        "duration_minutes": appt.get("duration_minutes") or 0,
        "location": appt.get("location__short_name"),
        "meeting_link": meeting_link,
        "status": appt.get("status"),
    }


def build_snapshot(appointment_id: str) -> tuple[AppointmentSnapshot, str, bool] | None:
    """Load an appointment/schedule-event and return ``(snapshot, provider_id, is_schedule_event)``.

    Returns ``None`` when the record is retracted (entered-in-error), gone, or has no provider — in
    every one of those cases there is nothing valid to push. ``is_schedule_event`` lets the real-time
    handler defer schedule events (admin holds) to the reconcile, avoiding the create-time race that
    let inbound-origin holds get pushed back to Google.
    """
    appt = (
        Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
        .values(*APPOINTMENT_FIELDS)
        .first()
    )
    if appt is None:
        return None
    provider_id = appt.get("provider__id")
    if not provider_id:
        return None
    return snapshot_from_values(appt), str(provider_id), _is_schedule_event(appt)


def google_origin_event_id(appointment_id: str) -> str | None:
    """Return the Google event id this Canvas record was imported from, or ``None``.

    A non-None result means the record originated in Google (we created it from an inbound event), so
    the outbound push must skip it — the Google event already exists and re-pushing would duplicate.
    """
    value = (
        AppointmentExternalIdentifier.objects.filter(
            appointment__id=appointment_id, system=GOOGLE_ORIGIN_SYSTEM
        )
        .values_list("value", flat=True)
        .first()
    )
    return str(value) if value else None
