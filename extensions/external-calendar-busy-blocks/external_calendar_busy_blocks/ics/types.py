from dataclasses import dataclass
from datetime import datetime


class IcsParseError(Exception):
    """Raised when an ICS body cannot be parsed."""


@dataclass(frozen=True)
class ParsedEvent:
    """A single VEVENT occurrence ready to be written to Canvas as an Admin block."""

    uid: str
    recurrence_id: str | None
    starts_at: datetime
    ends_at: datetime
    is_all_day: bool
    sequence: int
