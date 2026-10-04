from datetime import timedelta, timezone
from zoneinfo import ZoneInfo


def client_zone(tz_name: str, tz_offset_minutes: int) -> timezone | ZoneInfo:
    """Resolve the timezone to convert a client date and time with.

    A browser reports two things about where it sits. tz_name is the named
    IANA zone Intl.DateTimeFormat resolved on the page, and tz_offset_minutes
    is the fixed offset new Date().getTimezoneOffset() read at the moment
    someone clicked. The fixed offset only ever describes that one instant.
    A weekly series that spans a daylight saving change needs every
    occurrence converted at its own date, and only a named zone carries that
    rule, so a named zone is used whenever the browser resolved one. When
    tz_name is empty, or names a zone this runtime cannot look up, the fixed
    offset is the only fact available and stands in as before.
    """
    name = (tz_name or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError):
            pass
    return timezone(timedelta(minutes=-tz_offset_minutes))
