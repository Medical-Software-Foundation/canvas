"""Parse the `pre_appointment_days` plugin secret used by both Surescripts crons.

The secret is a comma-separated list of non-negative day offsets — each cron
fires for appointments whose date equals `today + offset`. Default `"1,7"`
preserves the original T+1 / T+7 behavior. Missing or malformed values fall
back to the default with a warning so the cron still runs.
"""

from logger import log

DEFAULT_DAYS = (1, 7)
SECRET_NAME = "pre_appointment_days"


def parse_days(raw: str | None) -> list[int]:
    """Parse a comma-separated list of non-negative integers from the secret.

    Returns the default `[1, 7]` on missing/malformed input. `0` is allowed
    (means "today's appointments"). Negative values are rejected so a typo
    can't accidentally look up past appointments.
    """
    if not raw or not raw.strip():
        return list(DEFAULT_DAYS)

    try:
        parsed = [int(p.strip()) for p in raw.split(",") if p.strip()]
    except ValueError:
        log.warning(
            "Surescripts %s: could not parse %r; falling back to %s"
            % (SECRET_NAME, raw, list(DEFAULT_DAYS))
        )
        return list(DEFAULT_DAYS)

    if not parsed or any(d < 0 for d in parsed):
        log.warning(
            "Surescripts %s: %r contains no valid non-negative offsets; "
            "falling back to %s" % (SECRET_NAME, raw, list(DEFAULT_DAYS))
        )
        return list(DEFAULT_DAYS)

    # Deduplicate while preserving order so the log line is readable.
    seen: set[int] = set()
    result: list[int] = []
    for d in parsed:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result
