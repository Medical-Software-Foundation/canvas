"""Durable once-only markers for actions that must not repeat.

These used to live in the plugins cache. That cache is backed by a Postgres
table with Django's default ``MAX_ENTRIES`` of 300 and ``CULL_FREQUENCY`` of 3,
and no ``OPTIONS`` override is set on it, so once the table passes 300 rows a
write deletes a third of them ordered by ``cache_key``.

Every marker this plugin kept there was load-bearing:

- "already reminded this appointment at this interval" — losing it re-sends
- "already sent the telehealth join" — losing it re-sends
- "already handled this inbound MessageSid" — losing it re-applies a patient's
  reply, duplicating the follow-up task and re-writing consent

Our keys share a prefix, so they sort together and a cull can take a contiguous
block of them at once. A cache is the wrong home for anything a correctness
guarantee rests on; the two remaining cache users in this plugin (the org-vars
lookup and the inbound-routing check) are pure speed-ups where eviction costs
only a re-query, and they stay where they are.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DateTimeField,
    Index,
    TextField,
    UniqueConstraint,
)


class SendClaim(CustomModel):
    """One row per action already taken. Presence means "do not do this again"."""

    # Which kind of action: "reminder", "telehealth", or "inbound".
    # Kept as a separate column rather than folded into `key` so the prune can
    # apply different retention per kind without parsing strings.
    scope = TextField()
    # Identifies the action within its scope: "<appointment-id>:<interval>" for
    # the two send scopes, the Twilio MessageSid for "inbound".
    key = TextField()
    claimed_at = DateTimeField(auto_now_add=True)

    class Meta:
        # The unique index is the whole mechanism, not an optimization.
        # `get_or_create` is only atomic because the database rejects the
        # loser's INSERT; without this a concurrent scan would read "absent"
        # twice and both invocations would send.
        #
        # Declared in Meta.constraints rather than as `unique=True` on a field,
        # which the SDK rejects outright, and not in Meta.indexes, where the DDL
        # pipeline would silently build a non-unique index.
        constraints = [
            UniqueConstraint(fields=["scope", "key"], name="uq_sc_scope_key"),
        ]
        # Names stay short for the same reason the delivery model's do: the DDL
        # pipeline emits "{schema}_{table}_{name}" and Postgres truncates
        # identifiers at 63 bytes, silently. This schema is 29 bytes, so
        # "canvas__appointment_reminders_sendclaim_uq_sc_scope_key" lands at 55
        # and "..._sc_claimed" at 50. Both fit; a longer class name would not.
        indexes = [
            # Supports the prune's range delete on claimed_at.
            Index(fields=["claimed_at"], name="sc_claimed"),
        ]
