import uuid

from django.db import models

from canvas_sdk.v1.data.base import CustomModel


class StaffCalendarFeed(CustomModel):
    """One row per provider that has connected a personal calendar feed."""

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["staff_id"],
                name="external_calendar_busy_blocks_feed_staff_unique",
            )
        ]

    id = models.UUIDField(default=uuid.uuid4, editable=False)
    staff_id = models.CharField(max_length=32)
    ics_url = models.TextField()
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_etag = models.CharField(max_length=256, null=True, blank=True)
    last_modified = models.CharField(max_length=64, null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ImportedEvent(CustomModel):
    """One row per (ICS UID, recurrence-id) -> Canvas Event id mapping."""

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["staff_id", "ics_uid", "recurrence_id"],
                name="external_calendar_busy_blocks_event_unique",
            )
        ]

    id = models.UUIDField(default=uuid.uuid4, editable=False)
    staff_id = models.CharField(max_length=32)
    ics_uid = models.CharField(max_length=512)
    recurrence_id = models.CharField(max_length=64, null=True, blank=True)
    canvas_event_id = models.CharField(max_length=64)
    sequence = models.IntegerField(default=0)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    last_seen = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
