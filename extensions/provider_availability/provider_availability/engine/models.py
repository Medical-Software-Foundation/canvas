"""Data models for provider availability rules and slots."""

import json
import uuid
from dataclasses import dataclass, field
import datetime as dt
from datetime import date, datetime, timedelta
from typing import Any, Optional, cast


DAYS_OF_WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _selected_weekdays(weekly_schedule: dict[str, Any]) -> list[int]:
    """Return weekday ints (Mon=0..Sun=6) that have at least one time window."""
    return sorted(
        DAYS_OF_WEEK.index(day)
        for day, windows in weekly_schedule.items()
        if windows and day in DAYS_OF_WEEK
    )


def recurrence_anchor(
    effective_start: Optional[date],
    frequency: str,
    weekly_schedule: dict[str, Any],
) -> Optional[date]:
    """Compute the anchor date for interval math.

    - Daily: the anchor is effective_start itself.
    - Weekly: the anchor is the first date on/after effective_start whose weekday
      is one of the selected weekdays in weekly_schedule. Returns None if no
      effective_start or no selected weekdays.
    """
    if effective_start is None:
        return None
    if frequency == "daily":
        return effective_start
    selected = _selected_weekdays(weekly_schedule)
    if not selected:
        return None
    for offset in range(7):
        candidate = effective_start + timedelta(days=offset)
        if candidate.weekday() in selected:
            return candidate
    return None


def date_in_pattern(
    candidate: date,
    effective_start: Optional[date],
    frequency: str,
    interval: int,
    weekly_schedule: dict[str, Any],
) -> bool:
    """Whether `candidate` falls on an in-pattern occurrence.

    For weekly frequency, also requires the candidate's weekday is in the schedule.
    For daily frequency, the schedule's weekday is irrelevant.
    """
    if interval < 1:
        return False
    if effective_start is not None and candidate < effective_start:
        return False
    if frequency == "daily":
        if effective_start is None:
            return True
        return (candidate - effective_start).days % interval == 0
    # weekly
    day_name = DAYS_OF_WEEK[candidate.weekday()]
    if not weekly_schedule.get(day_name):
        return False
    if interval == 1 or effective_start is None:
        return True
    anchor = recurrence_anchor(effective_start, frequency, weekly_schedule)
    if anchor is None:
        return True
    if candidate < anchor:
        return False
    return ((candidate - anchor).days // 7) % interval == 0


@dataclass
class TimeWindow:
    """A time window within a day."""

    # dt.time is blocked as an annotation in the Canvas sandbox.
    # Use Any here; values are always dt.time objects at runtime.
    start: Any
    end: Any

    def duration_minutes(self) -> int:
        start_dt = datetime.combine(date.today(), self.start)
        end_dt = datetime.combine(date.today(), self.end)
        return int((end_dt - start_dt).total_seconds() / 60)

    def overlaps(self, other: "TimeWindow") -> bool:
        return cast(bool, self.start < other.end and other.start < self.end)

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.strftime("%H:%M"), "end": self.end.strftime("%H:%M")}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "TimeWindow":
        return cls(
            start=dt.time.fromisoformat(data["start"]),
            end=dt.time.fromisoformat(data["end"]),
        )


@dataclass
class BufferTime:
    """Pre and post appointment buffer times in minutes."""

    pre: int = 0
    post: int = 15

    def to_dict(self) -> dict[str, int]:
        return {"pre": self.pre, "post": self.post}

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "BufferTime":
        return cls(pre=data.get("pre", 0), post=data.get("post", 15))


@dataclass
class BookingInterval:
    """Booking constraints for scheduling."""

    min_lead_hours: int = 24
    slot_granularity_minutes: int = 15

    def to_dict(self) -> dict[str, int]:
        return {
            "min_lead_hours": self.min_lead_hours,
            "slot_granularity_minutes": self.slot_granularity_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "BookingInterval":
        return cls(
            min_lead_hours=data.get("min_lead_hours", 24),
            slot_granularity_minutes=data.get("slot_granularity_minutes", 15),
        )


@dataclass
class DateOverride:
    """Override the weekly schedule for a specific date."""

    date: date
    is_closed: bool = False
    time_windows: list[TimeWindow] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "is_closed": self.is_closed,
            "time_windows": [w.to_dict() for w in self.time_windows],
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DateOverride":
        return cls(
            date=date.fromisoformat(data["date"]),
            is_closed=data.get("is_closed", False),
            time_windows=[TimeWindow.from_dict(w) for w in data.get("time_windows", [])],
            reason=data.get("reason", ""),
        )


@dataclass
class AdminBlock:
    """A manually created block of unavailable time."""

    provider_id: str
    start: datetime
    end: datetime
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reason: str = ""
    location_ids: list[str] = field(default_factory=list)
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    group_id: Optional[str] = None
    all_day: bool = False

    @property
    def cache_key(self) -> str:
        return f"pa:blocks:{self.provider_id}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reason": self.reason,
            "location_ids": self.location_ids,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "group_id": self.group_id,
            "all_day": self.all_day,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdminBlock":
        effective_start = None
        if data.get("effective_start"):
            effective_start = date.fromisoformat(data["effective_start"])
        effective_end = None
        if data.get("effective_end"):
            effective_end = date.fromisoformat(data["effective_end"])

        # Backward compat: location_id (str) → location_ids (list)
        location_ids = data.get("location_ids")
        if location_ids is None:
            old = data.get("location_id", "")
            location_ids = [old] if old else []

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            provider_id=data["provider_id"],
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            reason=data.get("reason", ""),
            location_ids=location_ids,
            effective_start=effective_start,
            effective_end=effective_end,
            group_id=data.get("group_id"),
            all_day=data.get("all_day", False),
        )


@dataclass
class RecurringBlock:
    """A recurring block of unavailable time (weekly or daily)."""

    provider_id: str
    weekly_schedule: dict[str, list[TimeWindow]] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reason: str = ""
    location_ids: list[str] = field(default_factory=list)
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    group_id: Optional[str] = None
    is_active: bool = True
    hold_type: str = "none"
    timezone: Optional[str] = None
    recurrence_frequency: str = "weekly"  # "weekly" | "daily"
    recurrence_interval: int = 1
    time_windows: list[TimeWindow] = field(default_factory=list)

    @property
    def cache_key(self) -> str:
        return f"pa:recurring_blocks:{self.provider_id}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "weekly_schedule": {
                day: [w.to_dict() for w in windows]
                for day, windows in self.weekly_schedule.items()
            },
            "reason": self.reason,
            "location_ids": self.location_ids,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "group_id": self.group_id,
            "is_active": self.is_active,
            "hold_type": self.hold_type,
            "timezone": self.timezone,
            "recurrence_frequency": self.recurrence_frequency,
            "recurrence_interval": self.recurrence_interval,
            "time_windows": [w.to_dict() for w in self.time_windows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecurringBlock":
        weekly_schedule = {}
        for day, windows in data.get("weekly_schedule", {}).items():
            weekly_schedule[day] = [TimeWindow.from_dict(w) for w in windows]

        effective_start = None
        if data.get("effective_start"):
            effective_start = date.fromisoformat(data["effective_start"])
        effective_end = None
        if data.get("effective_end"):
            effective_end = date.fromisoformat(data["effective_end"])

        time_windows = [
            TimeWindow.from_dict(w) for w in data.get("time_windows", [])
        ]

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            provider_id=data["provider_id"],
            weekly_schedule=weekly_schedule,
            reason=data.get("reason", ""),
            location_ids=data.get("location_ids", []),
            effective_start=effective_start,
            effective_end=effective_end,
            group_id=data.get("group_id"),
            is_active=data.get("is_active", True),
            hold_type=data.get("hold_type", "none"),
            timezone=data.get("timezone"),
            recurrence_frequency=data.get("recurrence_frequency", "weekly"),
            recurrence_interval=data.get("recurrence_interval", 1),
            time_windows=time_windows,
        )


@dataclass
class ProviderAvailabilityRule:
    """A single availability rule for a provider at a location for a visit type."""

    provider_id: str
    location_ids: list[str] = field(default_factory=list)
    visit_types: list[str] = field(default_factory=list)
    weekly_schedule: dict[str, list[TimeWindow]] = field(default_factory=dict)
    buffer_minutes: BufferTime = field(default_factory=BufferTime)
    booking_interval: BookingInterval = field(default_factory=BookingInterval)
    date_overrides: list[DateOverride] = field(default_factory=list)
    is_active: bool = True
    updated_at: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    effective_start: Optional[date] = None
    effective_end: Optional[date] = None
    group_id: Optional[str] = None
    reason: str = ""
    timezone: Optional[str] = None
    recurrence_frequency: str = "weekly"  # "weekly" | "daily"
    recurrence_interval: int = 1
    time_windows: list[TimeWindow] = field(default_factory=list)

    @property
    def cache_key(self) -> str:
        return f"pa:rules:{self.provider_id}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "location_ids": self.location_ids,
            "visit_types": self.visit_types,
            "weekly_schedule": {
                day: [w.to_dict() for w in windows]
                for day, windows in self.weekly_schedule.items()
            },
            "buffer_minutes": self.buffer_minutes.to_dict(),
            "booking_interval": self.booking_interval.to_dict(),
            "date_overrides": [o.to_dict() for o in self.date_overrides],
            "is_active": self.is_active,
            "updated_at": self.updated_at,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "group_id": self.group_id,
            "reason": self.reason,
            "timezone": self.timezone,
            "recurrence_frequency": self.recurrence_frequency,
            "recurrence_interval": self.recurrence_interval,
            "time_windows": [w.to_dict() for w in self.time_windows],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderAvailabilityRule":
        weekly_schedule = {}
        for day, windows in data.get("weekly_schedule", {}).items():
            weekly_schedule[day] = [TimeWindow.from_dict(w) for w in windows]

        date_overrides = [
            DateOverride.from_dict(o) for o in data.get("date_overrides", [])
        ]

        # Backward compat: location_id (str) → location_ids (list)
        location_ids = data.get("location_ids")
        if location_ids is None:
            old = data.get("location_id", "")
            location_ids = [old] if old else []

        # Backward compat: visit_type (str) → visit_types (list)
        visit_types = data.get("visit_types")
        if visit_types is None:
            old = data.get("visit_type", "")
            visit_types = [old] if old else []

        effective_start = None
        if data.get("effective_start"):
            effective_start = date.fromisoformat(data["effective_start"])
        effective_end = None
        if data.get("effective_end"):
            effective_end = date.fromisoformat(data["effective_end"])

        time_windows = [
            TimeWindow.from_dict(w) for w in data.get("time_windows", [])
        ]

        return cls(
            provider_id=data["provider_id"],
            location_ids=location_ids,
            visit_types=visit_types,
            weekly_schedule=weekly_schedule,
            buffer_minutes=BufferTime.from_dict(data.get("buffer_minutes", {})),
            booking_interval=BookingInterval.from_dict(data.get("booking_interval", {})),
            date_overrides=date_overrides,
            is_active=data.get("is_active", True),
            updated_at=data.get("updated_at", ""),
            id=data.get("id", str(uuid.uuid4())),
            effective_start=effective_start,
            effective_end=effective_end,
            group_id=data.get("group_id"),
            reason=data.get("reason", ""),
            timezone=data.get("timezone"),
            recurrence_frequency=data.get("recurrence_frequency", "weekly"),
            recurrence_interval=data.get("recurrence_interval", 1),
            time_windows=time_windows,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ProviderAvailabilityRule":
        return cls.from_dict(json.loads(json_str))


@dataclass
class AvailableSlot:
    """A single available time slot."""

    start: datetime
    end: datetime
    provider_id: str
    location_id: str = ""
    visit_type: str = ""

    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "provider_id": self.provider_id,
            "location_id": self.location_id,
            "visit_type": self.visit_type,
            "duration_minutes": str(self.duration_minutes()),
        }
