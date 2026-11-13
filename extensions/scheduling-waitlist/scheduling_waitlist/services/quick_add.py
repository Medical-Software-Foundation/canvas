"""Adding a patient to the waitlist in one click, on the broadest terms.

Reviewers asked for a quick action "that is the most general of all options",
because the common case is "put them on the list, they'll take what they can
get" and that was costing a modal, a form and a second click.

The general answer is spelled out as a submission and put through the same
:func:`validate_entry` the two forms post to, rather than assembling model fields
here. Building them directly would be shorter and would quietly become a second
implementation of the rules -- the priority default, the shelf life, the shape of
a preferred window -- which is exactly how the appointment-type dropdown came to
offer services the validator then refused.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from scheduling_waitlist.constants import PREFERENCE_ANY
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.entries import create_entry
from scheduling_waitlist.services.validation import validate_entry

# The time window meaning "no preference". A value rather than an empty string:
# ``_clean_window`` checks it against the offered windows.
ANY_WINDOW = "any"


class QuickAddRefused(Exception):
    """Validation refused the general submission.

    Carries the field errors so a caller can log which rule objected. Reaching
    this means the broadest possible request was rejected, which is a fault in
    the plugin or the instance rather than something a scheduler mistyped -- so
    it is raised rather than reported as a form error.
    """

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{field}: {text}" for field, text in errors.items()))
        self.errors = errors


def general_payload(patient_id: str) -> dict[str, Any]:
    """The submission a scheduler would make by accepting every default.

    Priority is left blank on purpose: the validator fills it from the configured
    default, so a practice that renames its bands does not have to be re-taught
    here.
    """
    return {
        "patient_id": str(patient_id),
        "appointment_type_id": PREFERENCE_ANY,
        "provider_preference": PREFERENCE_ANY,
        "location_preference": PREFERENCE_ANY,
        "priority": "",
        "preferred_window": ANY_WINDOW,
        "note": "",
    }


def quick_add(
    patient_id: str,
    *,
    created_by_dbid: Any,
    config: WaitlistConfig,
    today: date,
) -> Any:
    """Put a patient on the waitlist for anything, with anyone, anywhere.

    Raises :class:`QuickAddRefused` if validation objects, and
    :class:`~scheduling_waitlist.services.entries.DuplicateEntryError` if this
    patient already has a live general entry -- the caller decides what to show
    for each, because a button and an API answer them differently.
    """
    result = validate_entry(general_payload(patient_id), config=config, today=today)
    if not result.ok:
        raise QuickAddRefused(result.errors)

    return create_entry(created_by_dbid=created_by_dbid, **result.cleaned)
