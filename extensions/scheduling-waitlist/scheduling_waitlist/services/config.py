"""Reads plugin configuration out of secrets.

Every secret is parsed here so that "what happens when this is unset" is
answered in one place and can be tested against a plain dictionary.

Parsing never raises. A malformed optional value falls back to its default and
warns; a missing required value comes back empty or ``None`` and the caller
decides what to refuse. That split matters because "required" is per-consumer:
the scheduling team is required to raise a task but irrelevant to listing the
roster, and the shelf life is required to expire entries but irrelevant to
creating one.
"""

# Deliberately no ``from __future__ import annotations``: it turns every
# annotation into a string, and ``@dataclass`` then resolves those strings via
# ``sys.modules[cls.__module__]``. The Canvas sandbox execs each module into a
# synthetic scope that is not registered in ``sys.modules``, so the lookup
# returns None and the class body raises at import time -- meaning the plugin
# passes its tests and fails to load on the instance. Same applies in
# ``services/slot.py``, the other dataclass in this plugin.
from dataclasses import dataclass, field

from logger import log

from scheduling_waitlist.constants import (
    DEFAULT_DISPLAY_TIMEZONE,
    DEFAULT_ENFORCE_TIME_WINDOWS,
    DEFAULT_MAX_MATCHES_PER_TASK,
    DEFAULT_MIN_LEAD_TIME_HOURS,
    DEFAULT_PRIORITY_LABELS,
    DEFAULT_URGENT_LEAD_HOURS,
)

SECRET_SCHEDULING_TEAM = "WAITLIST_SCHEDULING_TEAM"
SECRET_APPOINTMENT_TYPES = "WAITLIST_APPOINTMENT_TYPES"
SECRET_PRIORITY_LABELS = "WAITLIST_PRIORITY_LABELS"
SECRET_TTL_DAYS = "WAITLIST_TTL_DAYS"
SECRET_MANAGER_ROLE_CODES = "WAITLIST_MANAGER_ROLE_CODES"
SECRET_ENFORCE_TIME_WINDOWS = "WAITLIST_ENFORCE_TIME_WINDOWS"
SECRET_MAX_MATCHES = "WAITLIST_MAX_MATCHES_PER_TASK"
SECRET_MIN_LEAD_TIME_HOURS = "WAITLIST_MIN_LEAD_TIME_HOURS"
SECRET_URGENT_LEAD_HOURS = "WAITLIST_URGENT_LEAD_HOURS"
SECRET_DISPLAY_TIMEZONE = "WAITLIST_DISPLAY_TIMEZONE"

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})


def parse_csv(raw: str | None) -> tuple[str, ...]:
    """Split a comma-separated secret, dropping blanks and surrounding space."""
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_upper_csv(raw: str | None) -> tuple[str, ...]:
    """Comma-separated values normalized to upper case, for code comparisons."""
    return tuple(value.upper() for value in parse_csv(raw))


def parse_positive_int(raw: str | None, *, name: str, default: int | None) -> int | None:
    """A whole number above zero, or ``default`` with a warning."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        log.warning(f"scheduling_waitlist: {name} is not a number; using {default}")
        return default
    if value <= 0:
        log.warning(f"scheduling_waitlist: {name} must be above zero; using {default}")
        return default
    return value


def parse_non_negative_int(raw: str | None, *, name: str, default: int) -> int:
    """A whole number of zero or more, or ``default`` with a warning."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        log.warning(f"scheduling_waitlist: {name} is not a number; using {default}")
        return default
    if value < 0:
        log.warning(f"scheduling_waitlist: {name} cannot be negative; using {default}")
        return default
    return value


def parse_bool(raw: str | None, *, default: bool) -> bool:
    """A flag. Anything not clearly true reads as false."""
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class WaitlistConfig:
    """Parsed plugin configuration."""

    scheduling_team: str = ""
    appointment_type_codes: tuple[str, ...] = ()
    priority_labels: tuple[str, ...] = field(default=DEFAULT_PRIORITY_LABELS)
    ttl_days: int | None = None
    manager_role_codes: tuple[str, ...] = ()
    enforce_time_windows: bool = DEFAULT_ENFORCE_TIME_WINDOWS
    max_matches_per_task: int = DEFAULT_MAX_MATCHES_PER_TASK
    min_lead_time_hours: int = DEFAULT_MIN_LEAD_TIME_HOURS
    urgent_lead_hours: int = DEFAULT_URGENT_LEAD_HOURS
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE

    @classmethod
    def from_secrets(cls, secrets: dict | None) -> "WaitlistConfig":
        """Build a configuration from the plugin's secrets. Never raises."""
        secrets = secrets or {}

        labels = parse_csv(secrets.get(SECRET_PRIORITY_LABELS))

        return cls(
            scheduling_team=(secrets.get(SECRET_SCHEDULING_TEAM) or "").strip(),
            appointment_type_codes=parse_csv(secrets.get(SECRET_APPOINTMENT_TYPES)),
            priority_labels=labels or DEFAULT_PRIORITY_LABELS,
            ttl_days=parse_positive_int(
                secrets.get(SECRET_TTL_DAYS), name=SECRET_TTL_DAYS, default=None
            ),
            manager_role_codes=parse_upper_csv(secrets.get(SECRET_MANAGER_ROLE_CODES)),
            enforce_time_windows=parse_bool(
                secrets.get(SECRET_ENFORCE_TIME_WINDOWS),
                default=DEFAULT_ENFORCE_TIME_WINDOWS,
            ),
            # Positive, not merely non-negative: a cap of zero would name no
            # patients and make every task useless.
            max_matches_per_task=parse_positive_int(
                secrets.get(SECRET_MAX_MATCHES),
                name=SECRET_MAX_MATCHES,
                default=DEFAULT_MAX_MATCHES_PER_TASK,
            )
            or DEFAULT_MAX_MATCHES_PER_TASK,
            min_lead_time_hours=parse_non_negative_int(
                secrets.get(SECRET_MIN_LEAD_TIME_HOURS),
                name=SECRET_MIN_LEAD_TIME_HOURS,
                default=DEFAULT_MIN_LEAD_TIME_HOURS,
            ),
            urgent_lead_hours=parse_non_negative_int(
                secrets.get(SECRET_URGENT_LEAD_HOURS),
                name=SECRET_URGENT_LEAD_HOURS,
                default=DEFAULT_URGENT_LEAD_HOURS,
            ),
            display_timezone=(
                secrets.get(SECRET_DISPLAY_TIMEZONE) or DEFAULT_DISPLAY_TIMEZONE
            ).strip()
            or DEFAULT_DISPLAY_TIMEZONE,
        )

    # -- derived --------------------------------------------------------

    def priority_rank(self, label: str) -> int:
        """Position of a label in the configured order; 0 is the most urgent.

        An unrecognized label sorts after every known one rather than jumping to
        the top, so a stale entry left behind by a configuration change never
        outranks a genuinely urgent patient.
        """
        normalized = (label or "").strip().casefold()
        for index, known in enumerate(self.priority_labels):
            if known.casefold() == normalized:
                return index
        return len(self.priority_labels)

    def is_known_priority(self, label: str) -> bool:
        """Whether a label is one this practice has configured."""
        return self.priority_rank(label) < len(self.priority_labels)

    @property
    def default_priority_label(self) -> str:
        """The least urgent configured label, used when a form omits one."""
        return self.priority_labels[-1] if self.priority_labels else ""
