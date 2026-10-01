"""Frequent, paced drain of the outbound (Canvas -> Google) backfill.

New providers (and any whose real-time pushes were missed) have a large backlog of appointments to
push into Google. Pushing them all in the daily reconcile hammered individual calendars into Google's
per-calendar rate limit, and the push path has no backoff, so the throttled writes were dropped —
which is why most providers never finished backfilling. This cron advances the least-recently-synced
providers a few at a time, each capped so no calendar is blasted; the tick cadence is the backoff
(the RestrictedPython sandbox has no ``time`` to sleep with). It is a cheap no-op once every provider
is fully backfilled. Outbound pushes go straight to Google, so there are no Canvas effects to return.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from gcal_sync.reconcile import drain_outbound_backfill


class OutboundBackfillDrainCron(CronTask):
    """Advances the least-recently-synced providers' Canvas->Google push a bounded amount each run."""

    SCHEDULE = "*/2 * * * *"

    def execute(self) -> list[Effect]:
        drain_outbound_backfill(self.secrets)
        return []
