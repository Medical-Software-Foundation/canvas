"""Ledger of slots we have already raised a task about."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    TextField,
    UniqueConstraint,
)

from scheduling_waitlist.models.proxies import AppointmentProxy


class SlotNotification(CustomModel):
    """One row per freed slot that has been announced to the scheduling team.

    This is the deduplication primitive. A single cancellation can reach the
    plugin more than once -- the same appointment cancelled, restored, and
    cancelled again, or a cancel and a no-show recorded against the same
    booking -- and every duplicate would otherwise put another task in front of
    a real person.

    It lives in a table rather than the cache deliberately. The SDK cache has no
    atomic add, caps entries at fourteen days, and evicts silently; a lost key
    there means a duplicate task rather than a slow page.
    """

    appointment = ForeignKey(
        AppointmentProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="waitlist_slot_notifications",
    )

    # sha256 over the slot's unchanging identity: which appointment, when, how
    # long, what type, whose, and where. The event type is deliberately left
    # out, so a cancellation and a no-show for the same booking collapse into
    # one announcement instead of two.
    slot_fingerprint = TextField(default="")

    task_id = TextField(default="")
    trigger_event = TextField(default="")
    entry_count = IntegerField(default=0)
    notified_at = DateTimeField(null=True)

    class Meta:
        indexes = [
            # The nightly prune.
            Index(fields=["notified_at"], name="wl_slotnotif_notified"),
        ]
        constraints = [
            UniqueConstraint(
                fields=["slot_fingerprint"],
                name="wl_slotnotif_unique_fingerprint",
            ),
        ]
