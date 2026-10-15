"""One searchable log line for every failure the background jobs catch and carry on past.

The 5-minute job and install keep going when one step or one provider fails,
so the rest still get their calendar updates. The cost is that a failure is
only a log line; this makes every such line the same shape, so one Elastic
query or alert finds them: ``PA_JOB_FAILED <step> <provider id or "all">``.
"""

from __future__ import annotations

from logger import log


def log_job_failure(step: str, provider_id: str = "all") -> None:
    """Log the exception being handled, with the standard prefix. Call from inside ``except``."""
    log.exception("PA_JOB_FAILED %s %s", step, provider_id or "all")
