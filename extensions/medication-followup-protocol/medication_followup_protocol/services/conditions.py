"""The condition vocabulary and its evaluation.

A condition decides whether a step still needs to fire on the morning it comes due. The
vocabulary is a registry rather than a chain of ifs, so a second condition is a new
function and one new row here, and no other unit changes.
"""

from __future__ import annotations

from typing import Callable
from typing import TYPE_CHECKING

from medication_followup_protocol.services.recheck import is_recheck_booked

if TYPE_CHECKING:
    from medication_followup_protocol.models import Enrollment

#: The name of the one condition this version carries.
RECHECK_NOT_BOOKED = "recheck_not_booked"


def _recheck_not_booked(enrollment: "Enrollment") -> bool:
    """The step still needs to fire while no recheck is booked."""
    return not is_recheck_booked(enrollment)


#: The vocabulary. A condition name maps to the predicate that says whether it holds.
#: Adding a condition is one function above and one row here.
CONDITIONS: dict[str, Callable[["Enrollment"], bool]] = {
    RECHECK_NOT_BOOKED: _recheck_not_booked,
}

#: What the configuration form offers. An unset condition means the step always fires.
CHOICES = [("", "Always"), (RECHECK_NOT_BOOKED, "The recheck is not booked")]


class UnknownCondition(ValueError):
    """Raised when a step carries a condition the vocabulary does not define."""


def holds(condition: str | None, enrollment: "Enrollment") -> bool:
    """Whether a step carrying this condition should fire for this enrolment.

    A step with no condition always fires. A step carrying a condition the vocabulary
    does not define raises, rather than defaulting either way, because both defaults are
    wrong in a way nobody would see.
    """
    if not condition:
        return True
    try:
        predicate = CONDITIONS[condition]
    except KeyError:
        raise UnknownCondition(condition) from None
    return predicate(enrollment)
