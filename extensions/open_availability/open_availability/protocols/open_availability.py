from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar, CalendarType, Event, EventRecurrence
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

DEFAULT_SCHEDULABLE_ROLES = "MD,DO,NP,PA"
DEFAULT_START_TIME = "08:00"
DEFAULT_END_TIME = "20:00"
DEFAULT_TIMEZONE = "America/New_York"
AVAILABILITY_YEARS = 25


def get_schedulable_roles(secrets: dict[str, str]) -> set[str]:
    """Parse the SCHEDULABLE_ROLES secret into a set of role abbreviations."""
    roles_str = secrets.get("SCHEDULABLE_ROLES", DEFAULT_SCHEDULABLE_ROLES)
    return {role.strip().upper() for role in roles_str.split(",") if role.strip()}


def is_staff_schedulable(staff: Staff, schedulable_roles: set[str]) -> bool:
    """Check if a staff member is schedulable based on their role."""
    role_abbrev = staff.top_role_abbreviation
    if not role_abbrev:
        return False
    return role_abbrev.upper() in schedulable_roles


def get_calendar_description(staff_key: str) -> str:
    """Generate a consistent calendar description for lookup."""
    return staff_key


def parse_time(value: str) -> tuple[int, int]:
    """Parse an HH:MM time string into (hour, minute). Raises ValueError on bad input."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM format, got: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Time out of range: {value}")
    return hour, minute


def get_availability_timezone(secrets: dict[str, str]) -> ZoneInfo:
    """Return the configured IANA timezone, falling back to DEFAULT_TIMEZONE on error."""
    tz_str = secrets.get("AVAILABILITY_TIMEZONE", DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(tz_str)
    except (KeyError, ValueError):
        log.error(
            f"AVAILABILITY_TIMEZONE '{tz_str}' is not a valid IANA timezone. "
            f"Falling back to {DEFAULT_TIMEZONE}"
        )
        return ZoneInfo(DEFAULT_TIMEZONE)


def get_availability_times(
    secrets: dict[str, str],
) -> tuple[tuple[int, int], tuple[int, int], ZoneInfo]:
    """Parse start time, end time, and timezone from secrets.

    Returns ((start_hour, start_min), (end_hour, end_min), tz).
    Falls back to defaults for any invalid value.
    """
    tz = get_availability_timezone(secrets)

    start_str = secrets.get("AVAILABILITY_START_TIME", DEFAULT_START_TIME)
    try:
        start = parse_time(start_str)
    except ValueError:
        log.warning(
            f"Invalid AVAILABILITY_START_TIME '{start_str}', "
            f"falling back to {DEFAULT_START_TIME}"
        )
        start = parse_time(DEFAULT_START_TIME)

    end_str = secrets.get("AVAILABILITY_END_TIME", DEFAULT_END_TIME)
    try:
        end = parse_time(end_str)
    except ValueError:
        log.warning(
            f"Invalid AVAILABILITY_END_TIME '{end_str}', "
            f"falling back to {DEFAULT_END_TIME}"
        )
        end = parse_time(DEFAULT_END_TIME)

    return start, end, tz


def create_availability_event(calendar_id: str, secrets: dict[str, str]) -> Effect:
    """Create a daily recurring 'Available' event on the given calendar.

    Reads AVAILABILITY_START_TIME, AVAILABILITY_END_TIME, and AVAILABILITY_TIMEZONE
    from secrets to determine the availability window. Times are converted from the
    configured timezone to UTC. Falls back to 08:00-20:00 America/New_York if secrets
    are missing or invalid.
    """
    (start_h, start_m), (end_h, end_m), tz = get_availability_times(secrets)

    now = datetime.now(timezone.utc)
    today_local = now.astimezone(tz)

    start_local = today_local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end_local = today_local.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    # If end is before or equal to start, it wraps to the next day
    if end_local <= start_local:
        end_local += timedelta(days=1)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    try:
        recurrence_end_local = start_local.replace(year=start_local.year + AVAILABILITY_YEARS)
    except ValueError:
        # Feb 29 + 25 years may land on a non-leap year
        recurrence_end_local = start_local.replace(
            year=start_local.year + AVAILABILITY_YEARS, day=start_local.day - 1
        )
    recurrence_end_utc = recurrence_end_local.astimezone(timezone.utc)

    log.info(
        f"[OpenAvailability] Event times: "
        f"start_local={start_local}, end_local={end_local}, "
        f"start_utc={start_utc}, ends_utc={end_utc}"
    )

    return Event(
        calendar_id=calendar_id,
        title="Available",
        starts_at=start_utc,
        ends_at=end_utc,
        recurrence_frequency=EventRecurrence.Daily,
        recurrence_interval=1,
        recurrence_ends_at=recurrence_end_utc,
    ).create()


class OpenAvailabilityOnActivation(BaseProtocol):
    """Creates a calendar with open availability when an eligible staff member is activated."""

    RESPONDS_TO = EventType.Name(EventType.STAFF_ACTIVATED)

    def compute(self) -> list[Effect]:
        """Create calendar and recurring availability event for activated staff."""
        staff_id = self.event.target.id
        schedulable_roles = get_schedulable_roles(self.secrets)

        try:
            staff = Staff.objects.get(id=staff_id)
        except Staff.DoesNotExist:
            log.warning(f"Staff not found for id: {staff_id}")
            return []

        if not is_staff_schedulable(staff, schedulable_roles):
            log.info(
                f"Staff {staff.full_name} (role: {staff.top_role_abbreviation}) "
                f"not in schedulable roles: {schedulable_roles}"
            )
            return []

        calendar_description = get_calendar_description(staff.id)

        # Check if a calendar already exists for this staff member
        existing_calendar = CalendarModel.objects.filter(
            description=calendar_description
        ).first()

        if existing_calendar:
            log.info(
                f"Calendar already exists for staff {staff.full_name}, using existing calendar"
            )
            calendar_id = str(existing_calendar.id)
            effects: list[Effect] = []
        else:
            log.info(f"Creating open availability calendar for staff: {staff.full_name}")
            # Generate a UUID for the calendar so we can reference it when creating the event
            calendar_id = str(uuid4())

            # Create the calendar
            calendar_effect = Calendar(
                id=calendar_id,
                provider=staff_id,
                type=CalendarType.Clinic,
                description=calendar_description,
            ).create()
            effects = [calendar_effect]

        try:
            effects.append(create_availability_event(calendar_id, self.secrets))
        except Exception:
            log.exception(
                f"Failed to create availability event for staff {staff.full_name}. "
                f"Calendar effect will still be applied."
            )

        return effects


class OpenAvailabilityOnDeactivation(BaseProtocol):
    """Updates availability event to end when a staff member is deactivated."""

    RESPONDS_TO = EventType.Name(EventType.STAFF_DEACTIVATED)

    def compute(self) -> list[Effect]:
        """Update recurring availability event to end on deactivation date."""
        staff_id = self.event.target.id
        schedulable_roles = get_schedulable_roles(self.secrets)

        try:
            staff = Staff.objects.get(id=staff_id)
        except Staff.DoesNotExist:
            log.warning(f"Staff not found for id: {staff_id}")
            return []

        if not is_staff_schedulable(staff, schedulable_roles):
            log.info(
                f"Staff {staff.full_name} (role: {staff.top_role_abbreviation}) "
                f"not in schedulable roles, skipping deactivation handling"
            )
            return []

        calendar_description = get_calendar_description(staff.id)

        # Find the calendar by description
        try:
            calendar = CalendarModel.objects.get(description=calendar_description)
        except CalendarModel.DoesNotExist:
            log.warning(
                f"No open-availability calendar found for staff {staff.full_name}. "
                f"Staff may have been created before plugin was installed."
            )
            return []

        # Find ALL active "Available" events on this calendar
        now = datetime.now(timezone.utc)
        active_events = calendar.events.filter(
            title="Available",
            recurrence_ends_at__gt=now,
        )
        if not active_events.exists():
            log.warning(
                f"No 'Available' events found on calendar for staff {staff.full_name}"
            )
            return []

        effects: list[Effect] = []
        for event in active_events:
            log.info(
                f"Ending open availability for staff: {staff.full_name} (event: {event.id})"
            )
            event_effect = Event(
                event_id=str(event.id),
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                recurrence_ends_at=now,
            ).update()
            effects.append(event_effect)

        log.info(
            f"Ended {len(effects)} active event(s) for staff: {staff.full_name}"
        )
        return effects
