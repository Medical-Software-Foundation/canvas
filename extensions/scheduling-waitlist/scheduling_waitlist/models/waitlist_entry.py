"""The roster row: one patient waiting for one kind of appointment."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateField,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    Q,
    TextField,
    UniqueConstraint,
)

from scheduling_waitlist.constants import (
    MATCHABLE_STATUSES,
    PREFERENCE_SPECIFIC,
    STATUS_WAITING,
)
from scheduling_waitlist.models.proxies import (
    AppointmentProxy,
    NoteTypeProxy,
    PatientProxy,
    PracticeLocationProxy,
    StaffProxy,
)


class WaitlistEntry(CustomModel):
    """A patient waiting to be scheduled.

    Note that the plugin DDL pipeline emits no NOT NULL constraints and no
    column defaults, so every ``default=`` here applies only when this code
    creates the row. Anything reading these columns has to tolerate ``None``.
    """

    patient = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="waitlist_entries",
    )

    # Null means "any appointment type will do".
    note_type = ForeignKey(
        NoteTypeProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries",
    )

    # "Any provider" is recorded as a value rather than inferred from a null
    # foreign key. Because the DDL emits no NOT NULL, a null column cannot be
    # told apart from one that was never filled in -- and reading null as "any"
    # would make a malformed row match every open slot, which is the wrong way
    # to fail. Stored explicitly, a malformed row matches nothing.
    provider_preference = TextField(default=PREFERENCE_SPECIFIC)
    desired_provider = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries_requested",
    )

    location_preference = TextField(default=PREFERENCE_SPECIFIC)
    desired_location = ForeignKey(
        PracticeLocationProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries",
    )

    # Rank orders the roster; label is the display string frozen at write time.
    # Storing only the label would mean re-reading configuration on every query
    # and silently reordering the whole backlog whenever an administrator edits
    # it. Storing only the rank would leave the roster unreadable after such an
    # edit. Both together survive a configuration change.
    priority_rank = IntegerField(default=0)
    priority_label = TextField(default="")

    # Structured from the start even though release 1 only displays it, so the
    # optional matching filter can be switched on later without a migration.
    # [{"days": [1], "start": "08:00", "end": "12:00"}], days per weekday(), 0=Mon.
    preferred_windows = JSONField(default=list)
    # Appointment times are UTC and PracticeLocation carries no timezone, so
    # without this "Tuesday morning" cannot be evaluated against a slot.
    preferred_windows_timezone = TextField(default="")
    # Whatever the structured form cannot express: "after school", "not the
    # week of the 14th". Displayed, never matched on.
    preferred_window_note = TextField(default="")

    note = TextField(default="")

    status = TextField(default=STATUS_WAITING)
    status_changed_at = DateTimeField(null=True)
    status_changed_by = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries_changed",
    )
    status_reason = TextField(default="")

    # Stamped when the entry is created, from the configured shelf life. Not
    # recomputed by the nightly job: editing the configuration must not
    # retroactively expire a backlog that was added under the old value.
    expires_on = DateField(null=True)

    # Set when the entry is auto-marked scheduled. Keeps that automatic change
    # auditable and reversible, and lets the matcher skip the entry belonging to
    # the appointment that just freed up.
    scheduled_appointment = ForeignKey(
        AppointmentProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries",
    )

    created_by = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        null=True,
        related_name="waitlist_entries_created",
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        # Foreign key columns are indexed automatically and declaring them again
        # raises, so only the non-key access paths appear here.
        indexes = [
            # Both the roster listing and the slot match: filter on status,
            # order by priority then age.
            Index(
                fields=["status", "priority_rank", "created_at"],
                name="wl_entry_status_priority",
            ),
            # The nightly age-out sweep.
            Index(fields=["status", "expires_on"], name="wl_entry_status_expiry"),
        ]
        constraints = [
            # One live entry per patient per appointment type, so a double-add
            # from two surfaces cannot quietly duplicate a row. Partial, so a
            # closed entry never blocks a fresh request for the same pair.
            UniqueConstraint(
                fields=["patient", "note_type"],
                condition=Q(status__in=list(MATCHABLE_STATUSES)),
                name="wl_entry_one_live_per_patient_type",
            ),
        ]
