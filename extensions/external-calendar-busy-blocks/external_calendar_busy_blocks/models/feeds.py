# Canvas discovers a plugin's custom-data models from the `<plugin>.models`
# package and creates a table per CustomModel subclass found there. The classes
# must be DEFINED within this package (their `__module__` under
# `external_calendar_busy_blocks.models.*`) — re-exporting them from elsewhere
# (e.g. `.data.models`) leaves `__module__` pointing outside the package, so the
# migration generator finds nothing and the tables are never created.
from django.db.models import (
    BooleanField,
    CharField,
    DateTimeField,
    IntegerField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class StaffCalendarFeed(CustomModel):
    """One row per provider that has connected a personal calendar feed."""

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["staff_id"],
                name="external_calendar_busy_blocks_feed_staff_unique",
            )
        ]

    staff_id = CharField(max_length=32)
    ics_url = TextField()
    is_active = BooleanField(default=True)
    last_sync_at = DateTimeField(null=True, blank=True)
    last_etag = CharField(max_length=256, null=True, blank=True)
    last_modified = CharField(max_length=64, null=True, blank=True)
    last_error = TextField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


class ImportedEvent(CustomModel):
    """One row per (ICS UID, recurrence-id) -> Canvas Event id mapping."""

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["staff_id", "ics_uid", "recurrence_id"],
                name="external_calendar_busy_blocks_event_unique",
            )
        ]

    staff_id = CharField(max_length=32)
    ics_uid = CharField(max_length=512)
    recurrence_id = CharField(max_length=64, null=True, blank=True)
    canvas_event_id = CharField(max_length=64)
    sequence = IntegerField(default=0)
    starts_at = DateTimeField()
    ends_at = DateTimeField()
    is_all_day = BooleanField(default=False)
    last_seen = DateTimeField()
    created_at = DateTimeField(auto_now_add=True)
