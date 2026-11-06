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
    IntegerField,
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
    # When the outbound reconcile last finished pushing this provider's whole window. The bounded
    # reconcile orders providers by this (nulls first) so a capped run rotates across the fleet and
    # successive runs converge — the outbound analog of ``CalendarSyncState`` for inbound full pulls.
    last_outbound_synced_at = DateTimeField(null=True)

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

    ``expanded_backfilled`` is set once the calendar's existing per-day holds have been marked in
    ``ExpandedEvent`` (see ``InboundSync._backfill_expanded``). Nullable, so it reads as unset on
    every row that predates it.
    """

    google_calendar_id = TextField()
    sync_token = TextField(default="")
    needs_full_resync = BooleanField(default=False)
    expanded_backfilled = BooleanField(null=True)
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

    ``last_applied_hash`` is the content hash of the event we last wrote to the hold; an inbound delta
    whose hash still matches is skipped, so an unchanged re-delivery doesn't re-save the appointment
    row (mirrors ``AppointmentEventMapping.last_pushed_hash`` on the outbound side).
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    canvas_appointment_id = TextField(default="")
    last_applied_hash = TextField(default="")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["google_event_id"], name="uq_inbound_event"),
        ]


class PendingHoldCreate(CustomModel):
    """Per-(calendar, event) marker that a hold create was issued and may still be applying.

    The ``ScheduleEvent`` create is applied asynchronously, so for a short window after we decide to
    create a hold there is no queryable Canvas hold yet. A re-delivered webhook for the SAME calendar
    within that window must not re-issue the create (doing so duplicated holds under load).

    This is deliberately keyed on ``(google_event_id, google_calendar_id)`` — NOT on the event id
    alone like ``InboundEventMapping``. A shared multi-attendee event is one event id across every
    attendee's calendar, so a single shared row (owned by whichever calendar wrote last) can't mark a
    create as pending for one attendee without un-marking it for another — the gap that let a replay
    mint a second hold for that attendee. A row per (calendar, event) gives each attendee its own
    marker that no other calendar can clobber, closing the cross-calendar re-create race.

    ``created_at`` is set explicitly (not ``auto_now_add``) so a past-grace re-create refreshes the
    window rather than being pinned to the first attempt.

    A multi-day event's holds are marked per day, with ``google_event_id`` set to the per-day value
    ``{event_id}:{YYYY-MM-DD}``, so only a day whose own create is still applying is held back and
    days added by a later edit are created straight away. The bare event id marks the single-hold
    path's create.
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    created_at = DateTimeField(null=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["google_event_id", "google_calendar_id"],
                name="uq_pending_hold_cal_event",
            ),
        ]


class RemovedDayHold(CustomModel):
    """A hold the sync cancelled itself, so the convergence guard does not treat it as out-of-band.

    Each covered day gets at most one hold for its whole life, so a hold cancelled out-of-band (a
    purge, or staff cancelling it in Canvas) is never re-created by a delta. A row here marks a
    cancelled hold as the sync's own doing. For a day the event stopped covering, the day may be
    held again if the event covers it again, and the row is deleted when that happens.

    ``google_event_id`` holds the per-day value ``{event_id}:{YYYY-MM-DD}``, the same value stamped on
    the hold, or the bare event id for a pre-expansion hold the sync retired (replaced by a per-day
    hold, or rebuilt as per-day holds by a re-import). Rows are per calendar like
    ``PendingHoldCreate``.
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["google_event_id", "google_calendar_id"],
                name="uq_removed_day_cal_event",
            ),
        ]


class AdoptedBareHold(CustomModel):
    """The day a pre-expansion (bare event id) hold was adopted onto, per calendar.

    A hold imported before per-day expansion carries the bare event id and is adopted as the first
    covered day's hold. If staff later cancel it, the convergence guard reads this row and keeps
    only that day unheld, so days a later edit adds still get holds. A bare hold cancelled before it
    was ever adopted has no row and keeps the whole event unheld. Deleted when the event is
    cancelled and on Purge or Reset.
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    adopted_date = TextField()
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["google_event_id", "google_calendar_id"],
                name="uq_adopted_bare_cal_event",
            ),
        ]


class ExpandedEvent(CustomModel):
    """A Google event this calendar's provider has per-day (``{event_id}:{date}``) holds for.

    Only an expanded event needs the prefix lookup on hold external ids, which no index can serve
    under the production collation. Every other single-day timed event uses the exact bare-id
    lookup, so this row is what tells an expanded event that later shrank to one timed day, or a
    cancellation (which carries no dates), to look for per-day holds. Deleted when the event is
    cancelled and on Purge or Reset.
    """

    google_calendar_id = TextField()
    google_event_id = TextField()
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["google_event_id", "google_calendar_id"],
                name="uq_expanded_event_cal_event",
            ),
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


class ReimportQueue(CustomModel):
    """One pending "rebuild this provider's holds" work item for the fleet re-import drain.

    "Re-import all" enqueues one row per active provider, and ``ReimportDrainCron`` pops a few per
    tick and re-imports them, deleting each row when its provider is done. A whole-roster rebuild in
    one call returns tens of thousands of hold effects in a single batch, which the platform doesn't
    apply reliably (the returned effects cross a gRPC message size ceiling and the whole batch is
    lost). Draining a few providers per cron tick keeps each returned batch small enough to always
    apply, and bounds per-tick memory so the worker never grows unbounded.

    Keyed unique on ``google_calendar_id`` so enqueuing is idempotent — clicking "Re-import all"
    twice, or while a drain is mid-flight, never doubles a provider's work item. ``attempts`` bounds
    retries so a provider whose calendar keeps erroring is dropped from the queue instead of wedging
    the drain forever.
    """

    google_calendar_id = TextField()
    attempts = IntegerField(default=0)
    enqueued_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["google_calendar_id"], name="uq_reimportqueue_cal"
            ),
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


class ProviderSyncLock(CustomModel):
    """A short-lived exclusivity lock for the per-provider admin actions (Reconcile / Re-import).

    The admin buttons run synchronously and can land on different plugin-runner containers, so two
    clicks race. Acquiring is atomic via the unique ``google_calendar_id`` constraint — a duplicate
    insert raises ``IntegrityError``, which the caller treats as "already running". ``acquired_at``
    lets a stale lock (a run that died before releasing) be reclaimed after a timeout so a provider
    never wedges permanently.
    """

    google_calendar_id = TextField()
    acquired_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["google_calendar_id"], name="uq_synclock_cal"),
        ]


__all__ = [
    "AppointmentEventMapping",
    "CalendarEventMapping",
    "CalendarSyncState",
    "InboundEventMapping",
    "PendingHoldCreate",
    "ProviderSyncLock",
    "ReimportQueue",
    "StaffCalendarMapping",
    "WatchChannel",
]
