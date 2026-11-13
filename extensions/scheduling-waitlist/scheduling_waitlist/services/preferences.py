"""What an entry will accept, one field at a time.

Three predicates, each answering "would this entry take a slot with this
attribute?". An entry accepts a value when it asked for exactly that, or when it
said anything would do.

They live in their own module because two callers need them and neither can
import the other: ``services/matching.py`` ANDs all three to decide who a freed
slot should name, while ``services/entries.py`` applies them one at a time for the
roster's filter bar.

Shared rather than written twice on purpose. They were written twice, and
disagreed: the roster filtered ``desired_provider_id=x``, so choosing a provider
hid every patient who said they would see anybody -- the people most likely to
take the slot -- while the freed-slot matcher named those same patients happily.
One rule, one implementation.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from scheduling_waitlist.constants import PREFERENCE_ANY


def accepts_note_type(note_type_dbid: Any) -> Q:
    """Entries that would accept an appointment of this type.

    A null ``note_type`` on an entry is how "any appointment type" is stored, so
    it accepts everything.
    """
    q = Q(note_type__isnull=True)
    if note_type_dbid is not None:
        q = q | Q(note_type_id=note_type_dbid)
    return q


def accepts_provider(provider_dbid: Any) -> Q:
    """Entries that would accept this provider.

    "Any provider" is a stored value rather than an absent foreign key, for the
    reason in ``models/waitlist_entry.py``: a null column cannot be told apart
    from one that was never filled in.
    """
    q = Q(provider_preference=PREFERENCE_ANY)
    if provider_dbid is not None:
        q = q | Q(desired_provider_id=provider_dbid)
    return q


def accepts_location(location_dbid: Any) -> Q:
    """Entries that would accept this location."""
    q = Q(location_preference=PREFERENCE_ANY)
    if location_dbid is not None:
        q = q | Q(desired_location_id=location_dbid)
    return q
