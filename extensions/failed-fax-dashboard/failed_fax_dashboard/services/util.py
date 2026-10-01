"""Small helpers shared by the dashboard and the scheduled job."""

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Canvas Bot is the Staff record that sends every fax made through the SDK's fax effect.
BOT_STAFF_ID = "5eede137ecfe4124b8b773040e33be14"

STAFF_PREFIX = "staff:"
TEAM_PREFIX = "team:"


def normalize_number(number: str | None) -> str:
    """Reduce a fax number to its digits so formatting differences still match."""
    return "".join(ch for ch in (number or "") if ch.isdigit())


def to_e164(number: str | None) -> str:
    """A fax number in E.164 form. Ten digits are taken as a US number."""
    digits = normalize_number(number)
    if not digits:
        return ""
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits


def last_ten(number: str | None) -> str:
    """The last 10 digits of a number, the part a directory match compares."""
    return normalize_number(number)[-10:]


def person_name(person: Any) -> str:
    """First and last name of a patient or staff member, or an empty string."""
    if person is None:
        return ""
    return f"{person.first_name} {person.last_name}".strip()


def name_key(first_name: str | None, last_name: str | None) -> str:
    """Sort key for a person: last name, then first name, lowercase."""
    return f"{(last_name or '').strip()} {(first_name or '').strip()}".strip().lower()


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into pieces of at most ``size`` (keeps query parameter counts bounded)."""
    return [items[start : start + size] for start in range(0, len(items), size)]


def practice_zone(environment: dict[str, Any] | None) -> ZoneInfo:
    """The instance's time zone, UTC when it is not set."""
    name = (environment or {}).get("INSTALLATION_TIME_ZONE") or "UTC"
    return ZoneInfo(name)


def format_local(moment: datetime, zone: ZoneInfo) -> str:
    """For example ``Oct 1, 3:42 PM``, in the practice's time zone."""
    local = moment.astimezone(zone)
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{local:%b} {local.day}, {hour}:{local.minute:02d} {suffix}"


def due_today(now: datetime, zone: ZoneInfo) -> datetime:
    """Noon today in the practice's time zone, so the calendar day holds for every viewer."""
    local = now.astimezone(zone)
    return datetime(local.year, local.month, local.day, 12, tzinfo=zone).astimezone(timezone.utc)


def seconds_apart(first: datetime, second: datetime) -> float:
    """Seconds from ``first`` to ``second`` (negative when second is earlier)."""
    return (second - first) / timedelta(seconds=1)


def full_url(environment: dict[str, Any] | None, path: str) -> str:
    """A full web address for an internal path, so task comments render it as a link."""
    identifier = (environment or {}).get("CUSTOMER_IDENTIFIER")
    if not identifier or not path.startswith("/"):
        return path
    return f"https://{identifier}.canvasmedical.com{path}"
