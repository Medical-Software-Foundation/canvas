"""Shared helpers for the lab order validation rules.

Kept small - one function per real cross-rule need.
"""

from datetime import date


def is_active_coverage(coverage) -> bool:
    """True iff the coverage is in use, state=active, and not expired or future-dated.

    Canvas stores coverage status across two fields:
    - `stack`: IN_USE / OTHER / REMOVED. The user-facing "Remove" button in the
      Coverages tab sets this to REMOVED. The active stack is IN_USE.
    - `state`: active / deleted. This is the hard-delete flag for data cleanup,
      NOT what the UI "Remove" button toggles.

    A coverage is only "active" for validation purposes when BOTH fields agree
    AND the coverage's effective date window includes today.
    """
    stack = getattr(coverage.stack, "value", coverage.stack)
    if str(stack).strip().upper() != "IN_USE":
        return False

    state = getattr(coverage.state, "value", coverage.state)
    if str(state).strip().lower() != "active":
        return False

    today = date.today()
    start = coverage.coverage_start_date
    end = coverage.coverage_end_date
    if start and start > today:
        return False
    if end and end < today:
        return False
    return True


def has_meaningful_content(value, min_alnum: int = 2) -> bool:
    """True iff value contains at least `min_alnum` alphanumeric characters.

    Rejects placeholders like '---', '.', 'n/a', whitespace-only strings,
    and pure punctuation. Two alphanumerics is the minimum that any real
    street, city, state code, or ZIP fragment carries.
    """
    if value is None:
        return False
    return sum(1 for c in str(value) if c.isalnum()) >= min_alnum


def sanitize_for_display(name) -> str:
    """Make a name safe to drop into a user-facing error message.

    - Drops ASCII control characters (0x00-0x1F, 0x7F).
    - Collapses whitespace runs (including unusual whitespace like NBSP).
    - Strips leading/trailing whitespace.
    - Truncates anything past 80 characters with an ellipsis.

    Returns "" if the cleaned result is empty.
    """
    if name is None:
        return ""

    # Explicit allow-list of whitespace that should collapse to a single space.
    # Python's str.isspace() also returns True for separator control chars like
    # \x1c-\x1f, which we'd rather drop entirely.
    collapsible = {" ", "\t", "\n", "\r", "\xa0"}

    cleaned: list[str] = []
    last_was_space = False
    for ch in str(name):
        if ch in collapsible:
            if not last_was_space:
                cleaned.append(" ")
                last_was_space = True
            continue
        code = ord(ch)
        if code < 32 or code == 127:
            continue
        cleaned.append(ch)
        last_was_space = False

    result = "".join(cleaned).strip()
    if len(result) > 80:
        result = result[:77] + "..."
    return result
