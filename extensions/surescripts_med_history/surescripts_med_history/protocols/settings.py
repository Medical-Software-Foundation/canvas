"""Parse the boolean plugin secrets that configure the med-history modal.

`commit_medication_statements` controls whether an `+ Add` from the modal drops
the `MedicationStatement` into the note as a staged (uncommitted) command the
provider still has to commit, or commits it outright. Default is uncommitted,
which preserves the original behavior and keeps a human in the loop before the
statement lands on the chart.

`mock_history_data` injects a fixed set of fake Surescripts rows into the modal
so the workflow can be demoed on instances where no real history exists. Default
off — it must never be on in a live clinical environment.
"""

from logger import log

COMMIT_SECRET_NAME = "commit_medication_statements"
MOCK_SECRET_NAME = "mock_history_data"

DEFAULT_COMMIT = False
DEFAULT_MOCK = False

_TRUTHY = {"true", "t", "yes", "y", "1", "on", "committed", "commit"}
_FALSY = {"false", "f", "no", "n", "0", "off", "uncommitted", "staged"}


def parse_bool(raw: str | bool | None, name: str, default: bool) -> bool:
    """Parse a boolean plugin secret.

    Accepts the usual truthy/falsy spellings plus `committed`/`uncommitted` so
    the commit secret reads naturally either way. Missing, blank, or
    unrecognized values fall back to `default` rather than guessing;
    unrecognized ones also log a warning.
    """
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default

    value = str(raw).strip().lower()
    if not value:
        return default
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False

    log.warning(
        "Surescripts %s: could not parse %r; falling back to %s" % (name, raw, default)
    )
    return default


def parse_commit(raw: str | bool | None) -> bool:
    """Whether `+ Add` should commit the MedicationStatement command."""
    return parse_bool(raw, COMMIT_SECRET_NAME, DEFAULT_COMMIT)


def parse_mock(raw: str | bool | None) -> bool:
    """Whether to inject demo/test medication-history rows into the modal."""
    return parse_bool(raw, MOCK_SECRET_NAME, DEFAULT_MOCK)
