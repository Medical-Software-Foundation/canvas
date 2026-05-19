from __future__ import annotations

from datetime import UTC, datetime, timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from recent_patients.models.recent_patient_interaction import RecentPatientInteraction

RETENTION_DAYS = 7


class PruneOldInteractions(CronTask):
    """Nightly: drop interactions older than 7 days.

    "Recent" means the last week — matches the UI's day-bucket vocabulary
    (Today / Yesterday / This Week). Runs at 03:00 UTC so it doesn't compete
    with daytime workflow load.
    """

    SCHEDULE = "0 3 * * *"

    def execute(self) -> list[Effect]:
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        deleted, _ = RecentPatientInteraction.objects.filter(
            occurred_at__lt=cutoff,
        ).delete()
        log.info(f"PruneOldInteractions deleted {deleted} rows older than {cutoff.isoformat()}")
        return []
