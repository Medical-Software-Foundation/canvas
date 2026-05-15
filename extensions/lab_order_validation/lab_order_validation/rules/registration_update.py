"""Rule 2: Detect the legacy "update registration" / sign-only state.

This is the duplicate-coverage class of bugs where the same patient has
two active coverages from the same payer (Transactor). Today the Canvas UI
hides the duplicate but the data state breaks the Send button - Health
Gorilla returns a 422 or the order is silently dropped.

Detection here is best-effort. False alarms can be dismissed via the
note-header "Acknowledge coverage warning" button.
"""

from collections import Counter

from lab_order_validation.rules._helpers import is_active_coverage, sanitize_for_display


def _active_coverages_with_issuer(patient) -> list:
    return [
        c
        for c in patient.coverages.all()
        if is_active_coverage(c) and c.issuer is not None
    ]


def check(patient) -> list[str]:
    """Return a list of error strings; empty means pass."""
    active = _active_coverages_with_issuer(patient)
    if not active:
        return []

    issuer_dbids = [c.issuer.dbid for c in active]
    counts = Counter(issuer_dbids)
    duplicates = [dbid for dbid, n in counts.items() if n > 1]
    if not duplicates:
        return []

    duplicate_payer_names = sorted(
        {sanitize_for_display(c.issuer.name) for c in active if c.issuer.dbid in duplicates}
    )
    payer_list = ", ".join(f"'{name}'" for name in duplicate_payer_names)
    return [
        f"Duplicate active coverages from {payer_list}. "
        "Remove duplicates in the Coverages tab."
    ]
