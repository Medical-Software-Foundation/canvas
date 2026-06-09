from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.v1.data.calendar import Calendar
from canvas_sdk.v1.data.staff import Staff


def find_admin_calendar_id(staff: Staff) -> str | None:
    """Return the id of the staff's Administrative calendar, or None."""
    calendar_id = (
        Calendar.objects.for_calendar_name(
            provider_name=staff.full_name,
            calendar_type=CalendarType.Administrative,
            location=None,
        )
        .values_list("id", flat=True)
        .last()
    )
    # `id` is a UUID. The Event effect json-serializes calendar_id as-is, so a
    # UUID object raises "Object of type UUID is not JSON serializable". Return
    # a string so the downstream Event(...).create() payload serializes.
    return str(calendar_id) if calendar_id is not None else None
