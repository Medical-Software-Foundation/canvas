"""Plugin configuration, parsed from the instance's plugin variables.

Deliberately no ``from __future__ import annotations`` in this module. That
import turns every annotation into a string, and ``@dataclass`` then resolves
those strings via ``sys.modules[cls.__module__]``. The Canvas sandbox execs each
module into a synthetic scope that is not registered in ``sys.modules``, so the
lookup returns None and the class body raises at import time -- meaning the
plugin passes its tests and fails to load on the instance.
"""

from dataclasses import dataclass, field
from typing import Any

from logger import log

from patient_resources.constants import (
    DEFAULT_ADMIN_ROLE_DOMAINS,
    KNOWN_ROLE_DOMAINS,
    SECRET_ADMIN_ROLE_DOMAINS,
    SECRET_ADMIN_STAFF_IDS,
)


def parse_upper_csv(raw: Any) -> tuple[str, ...]:
    """Split a comma-separated string into upper-cased, de-blanked tokens."""
    if raw is None:
        return ()
    tokens = [token.strip().upper() for token in str(raw).split(",")]
    return tuple(token for token in tokens if token)


def parse_csv(raw: Any) -> tuple[str, ...]:
    """Split a comma-separated string, preserving case."""
    if raw is None:
        return ()
    tokens = [token.strip() for token in str(raw).split(",")]
    return tuple(token for token in tokens if token)


@dataclass(frozen=True)
class PatientResourcesConfig:
    """Who may curate the resource library.

    That is the whole of this plugin's configuration. Page sizes, field lengths
    and batch caps are constants rather than variables: they are engineering
    limits, not practice policy, and a reference plugin should work out of the
    box without anyone choosing them.
    """

    admin_role_domains: tuple[str, ...] = field(default=DEFAULT_ADMIN_ROLE_DOMAINS)
    admin_staff_ids: tuple[str, ...] = ()

    @classmethod
    def from_secrets(cls, secrets: dict | None) -> "PatientResourcesConfig":
        """Build a configuration from the plugin's variables. Never raises.

        A malformed value logs and falls back, because a configuration error must
        not take the plugin down. The one thing that never happens is falling
        back in a way that grants access: see the branches below.
        """
        values = secrets or {}

        domains: tuple[str, ...]
        raw_domains = values.get(SECRET_ADMIN_ROLE_DOMAINS)
        if raw_domains is None:
            # Key absent: the practice has not configured this. Default to
            # administrative roles. Not a fail-open -- it still requires a real
            # administrative role -- but it does mean a fresh install has a
            # working admin without anyone looking up a staff UUID first.
            domains = DEFAULT_ADMIN_ROLE_DOMAINS
        else:
            requested = parse_upper_csv(raw_domains)
            if not requested:
                # Present but blank. An operator who emptied this meant to switch
                # curation off, so nobody gets it.
                log.warning(
                    f"{SECRET_ADMIN_ROLE_DOMAINS} is set but empty; "
                    "no staff member can curate the resource library"
                )
                domains = ()
            else:
                known = tuple(d for d in requested if d in KNOWN_ROLE_DOMAINS)
                unknown = [d for d in requested if d not in KNOWN_ROLE_DOMAINS]
                if unknown:
                    log.warning(
                        f"{SECRET_ADMIN_ROLE_DOMAINS} contains unrecognized role "
                        f"domain(s) {unknown}; expected any of {list(KNOWN_ROLE_DOMAINS)}"
                    )
                if not known:
                    # Every token was junk. Reverting to the default here would
                    # silently undo a deliberate restriction, so this denies
                    # instead and says why.
                    log.error(
                        f"{SECRET_ADMIN_ROLE_DOMAINS} matched no known role domain; "
                        "no staff member can curate the resource library"
                    )
                domains = known

        return cls(
            admin_role_domains=domains,
            admin_staff_ids=parse_csv(values.get(SECRET_ADMIN_STAFF_IDS)),
        )
