"""Periodic full reconciliation between Canvas and Google (spec §4.1, §6.4).

Runs once a day and delegates to :mod:`gcal_sync.reconcile`, which (1) runs an inbound delta pull per
calendar so an invalidated ``syncToken`` recovers, and (2) re-pushes every upcoming non-cancelled
Canvas appointment so Google reflects Canvas even if a live push was missed.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from gcal_sync.reconcile import reconcile_all


class ReconciliationCron(CronTask):
    """Daily safety net that re-converges Canvas and Google."""

    SCHEDULE = "30 5 * * *"

    def execute(self) -> list[Effect]:
        _stats, effects = reconcile_all(self.secrets)
        # Apply any Google->Canvas admin-hold effects discovered during the inbound recovery pass.
        return effects
