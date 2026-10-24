"""Who may open the configuration screen.

This is the one setting that stays in Canvas administration, and staying there is
the point rather than a limitation. A plugin cannot write its own installation
variables, so the list of people allowed to change policy cannot be edited from
inside the screen it guards.

Empty means nobody. The screen is invisible until somebody is deliberately added,
which is the safe direction for a setting that decides whether a patient is
reviewed for discharge.

Canvas hands a plugin the staff member's key, a thirty two character hex string,
and not the integer shown beside a user in the administration user list. Copying
that integer is the obvious mistake and it fails silently, the screen simply
never appears. Two things here answer that. A refusal is logged with the key that
was actually presented, and the screen shows each person their own key so an
administrator can be handed the right value rather than guessing at it.
"""

from typing import Any

from logger import log


class AccessList:
    """The staff keys permitted to open the configuration screen."""

    def __init__(self, raw: Any) -> None:
        # Whitespace and commas both separate. The administration field is
        # multiline and a key contains neither, so accepting both means nobody
        # has to remember which one this field wanted.
        text = f"{raw or ''}".replace(",", " ")
        self._keys = frozenset(part.strip().lower() for part in text.split() if part.strip())

    def is_empty(self) -> bool:
        """True when nobody has been granted access yet."""
        return not self._keys

    def permits(self, staff_key: str) -> bool:
        """True when this staff key may open the configuration screen."""
        key = f"{staff_key or ''}".strip().lower()
        if not key:
            return False
        if key in self._keys:
            return True
        # Logged so a wrong or wrongly formatted identifier is discoverable.
        # Without this the only symptom is a screen that never appears, which is
        # indistinguishable from the plugin being broken.
        log.info(f"attendance configuration refused for presented staff key {key}")
        return False
