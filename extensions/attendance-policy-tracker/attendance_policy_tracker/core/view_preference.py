"""The one view preference the whole clinic shares.

Stored beside the policy in the plugin's own namespace and deliberately not part
of it. Whether somebody wants to see visits that do not count changes nothing
about counting and nothing about who a visit counts against, so it is kept out of
the policy object, off the configuration screen, and out of the validation that
keeps policy coherent. The policy loader ignores names it does not recognise,
which is what lets this share the same table without a schema change.

Shared rather than per person on purpose. The requirement is that switching it on
stays on wherever a person goes and whichever record they open, and there is no
per person storage here to hold that. The consequence is worth stating, this is
the one stored setting a member of staff changes for everybody, and the only one
not gated behind the configuration permission. Gating it would leave most people
unable to move a switch on their own screen, which is the opposite of what was
asked for.

Functions rather than a class, because there is nothing to hold between calls.
They are handed the store rather than reaching for one, so the same store
contract the policy already depends on is the only thing here.
"""

from typing import Any

SHOW_NON_COUNTING = "show_non_counting_visits"

_TRUE = "true"
_FALSE = "false"


def truthy(value: Any) -> bool:
    """Whether this value means on, from a browser or from storage.

    Both a real boolean and the word arrive here, one from a page sending JSON
    and one from a store that keeps every value as text, and neither side should
    have to know which the other used.
    """
    return value is True or f"{value}".strip().lower() == _TRUE


def show_non_counting(store: Any) -> bool:
    """True when the surface should show visits that do not count."""
    return truthy(store.read().get(SHOW_NON_COUNTING, ""))


def set_show_non_counting(store: Any, value: bool) -> None:
    """Store the shared preference, for everybody.

    Off is written as the word rather than as an empty value, because the store
    treats empty as a deletion and a deleted name cannot be told apart from one
    that was never set. Off has to be storable in its own right, otherwise
    switching it off would read back as unset and whatever the default happens to
    be would decide.
    """
    store.write({SHOW_NON_COUNTING: _TRUE if value else _FALSE})
