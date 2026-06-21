"""Persistent state for the two-way Google Calendar sync (spec §5).

CustomModels must live in the plugin's ``models/`` package and the plugin must declare a
``custom_data`` namespace in ``CANVAS_MANIFEST.json`` — otherwise Canvas logs "has no custom_data -
skipping schema setup" and never creates these tables. Defined directly in ``__init__.py`` (the
documented pattern) so the DDL scanner registers each model exactly once.

| Model                       | Keyed by        | Purpose                                              |
|-----------------------------|-----------------|------------------------------------------------------|
| ``StaffCalendarMapping``    | staff id        | Which Workspace calendar a provider's appts sync to. |
| ``AppointmentEventMapping`` | appointment id  | Target Google event for updates/deletes; echo id.    |
| ``CalendarSyncState``       | calendar id     | ``syncToken`` for incremental ``events.list``.       |
| ``WatchChannel``            | channel id      | ``events.watch`` channel lifecycle (renew/stop).     |

Per the SDK, ``not null``/``max_length`` are not DB-enforced — code owns required-field discipline.
Uniqueness IS enforced via ``Meta.constraints``.
"""

from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel


class StaffCalendarMapping(CustomModel):
    """Maps a Canvas staff member to the Google Workspace calendar we sync into.

    Identity (``subject`` for domain-wide delegation) is the calendar's email address, which for a
    Workspace user is the same as their primary calendar id. ``active=False`` lets an admin pause a
    provider's sync without losing the mapping.
    """

    canvas_staff_id = TextField()
    google_calendar_id = TextField()
    active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["canvas_staff_id"], name="uq_staffcal_staff"),
        ]


class AppointmentEventMapping(CustomModel):
    """Links a Canvas appointment to the Google event we created for it.

    ``last_pushed_hash`` is the content hash of the event body Canvas most recently wrote. On an
    inbound webhook delta we compare the incoming event's content against this hash to recognise and
    drop our own echo (spec §6.1).
    """

    canvas_appointment_id = TextField()
    google_calendar_id = TextField()
    google_event_id = TextField()
    last_pushed_hash = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["canvas_appointment_id"], name="uq_apptevt_appt"),
        ]
        indexes = [
            # Webhook deltas arrive keyed by Google event id; we look the mapping up in reverse.
            Index(fields=["google_event_id"]),
        ]


class CalendarSyncState(CustomModel):
    """Per-calendar incremental sync cursor.

    ``sync_token`` is Google's opaque cursor for ``events.list``. When Google returns ``410 Gone``
    the token is invalid; we clear it and set ``needs_full_resync`` so the next reconcile does a full
    pull instead of an incremental one (spec §6.4).
    """

    google_calendar_id = TextField()
    sync_token = TextField(default="")
    needs_full_resync = BooleanField(default=False)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["google_calendar_id"], name="uq_syncstate_cal"),
        ]


class InboundEventMapping(CustomModel):
    """Tracks Google events we imported into Canvas as admin holds (Google → Canvas direction).

    Written synchronously the moment we decide to create a Canvas schedule event, so a re-delivered
    webhook for the same Google event is recognised and not imported twice (the Canvas create effect
    is applied asynchronously, so we can't rely on querying Canvas to dedup in the same request).
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    canvas_appointment_id = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["google_event_id"], name="uq_inbound_event"),
        ]


class CalendarEventMapping(CustomModel):
    """Links a Canvas Calendar ``Event`` (admin block) to the Google event we created for it.

    Separate from ``AppointmentEventMapping`` because blocks are a different Canvas model (calendar
    events, not appointments) and the block sweep needs to detect removed blocks by diffing the
    current block set against these rows.
    """

    canvas_event_id = TextField()
    google_calendar_id = TextField()
    google_event_id = TextField()
    last_pushed_hash = TextField(default="")
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["canvas_event_id"], name="uq_calevt_event"),
        ]


class WatchChannel(CustomModel):
    """An active ``events.watch`` push channel for one calendar.

    Channels expire in ≤7 days; ``ChannelRenewalCron`` stops and recreates them before
    ``expiration``. ``channel_id`` is the value we mint and send to Google; ``resource_id`` is what
    Google returns and what ``channels.stop`` requires.
    """

    google_calendar_id = TextField()
    channel_id = TextField()
    resource_id = TextField()
    expiration = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["channel_id"], name="uq_watch_channel"),
        ]
        indexes = [
            Index(fields=["google_calendar_id"]),
        ]


__all__ = [
    "AppointmentEventMapping",
    "CalendarEventMapping",
    "CalendarSyncState",
    "InboundEventMapping",
    "StaffCalendarMapping",
    "WatchChannel",
]
