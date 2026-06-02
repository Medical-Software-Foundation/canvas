import uuid

import pytest
from django.db import IntegrityError

from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)


@pytest.mark.django_db
def test_staff_calendar_feed_can_be_saved() -> None:
    feed = StaffCalendarFeed(
        staff_id="staff-abc",
        ics_url="https://calendar.google.com/calendar/ical/.../basic.ics",
        is_active=True,
    )
    feed.save()
    assert feed.dbid is not None


@pytest.mark.django_db
def test_staff_calendar_feed_staff_id_is_unique() -> None:
    StaffCalendarFeed(
        staff_id="staff-abc",
        ics_url="https://example.com/a.ics",
    ).save()
    with pytest.raises(IntegrityError):
        StaffCalendarFeed(
            staff_id="staff-abc",
            ics_url="https://example.com/b.ics",
        ).save()


@pytest.mark.django_db
def test_imported_event_can_be_saved() -> None:
    from datetime import datetime, timezone
    canvas_event_id = str(uuid.uuid4())
    record = ImportedEvent(
        staff_id="staff-abc",
        ics_uid="event-uid-1@google.com",
        recurrence_id=None,
        canvas_event_id=canvas_event_id,
        sequence=0,
        starts_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        is_all_day=False,
        last_seen=datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc),
    )
    record.save()
    assert record.dbid is not None


@pytest.mark.django_db
def test_imported_event_unique_per_staff_uid_recurrence() -> None:
    from datetime import datetime, timezone
    common = dict(
        staff_id="staff-abc",
        ics_uid="event-1@google.com",
        recurrence_id="20260601T140000Z",
        canvas_event_id=str(uuid.uuid4()),
        sequence=0,
        starts_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        is_all_day=False,
        last_seen=datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc),
    )
    ImportedEvent(**common).save()
    with pytest.raises(IntegrityError):
        ImportedEvent(**{**common, "canvas_event_id": str(uuid.uuid4())}).save()
