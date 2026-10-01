"""Drains the fleet re-import queue a few providers at a time.

"Re-import all" enqueues every active provider (a fast, synchronous DB write) and this cron does the
actual rebuilds — a small batch per tick, each returning its hold effects for Canvas to apply. A
whole-roster rebuild in one call returns tens of thousands of effects in a single batch that the
platform can't apply reliably; draining a few providers per tick keeps each returned batch small
enough to always land, and bounds per-tick memory. The cron is a cheap no-op when the queue is empty.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from gcal_sync.reconcile import drain_reimport_queue


class ReimportDrainCron(CronTask):
    """Rebuilds a few queued providers' holds each run until the fleet re-import queue is empty."""

    SCHEDULE = "*/2 * * * *"

    def execute(self) -> list[Effect]:
        _totals, effects = drain_reimport_queue(self.secrets)
        return effects
