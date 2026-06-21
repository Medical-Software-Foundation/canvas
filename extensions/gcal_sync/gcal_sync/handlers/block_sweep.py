"""Frequent sweep that pushes provider admin blocks (lunch/PTO) to Google.

Admin blocks are Calendar ``Event`` objects with no lifecycle events, so they can't sync in real
time like appointments. This cron sweeps every enrolled provider's Administrative-calendar blocks on
a short interval; it only makes Google calls when a block actually changed or was removed, so a
steady state is cheap.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from gcal_sync.blocks import sync_all_blocks
from gcal_sync.models import StaffCalendarMapping


class BlockSweepCron(CronTask):
    """Pushes admin-block changes to Google every 15 minutes."""

    SCHEDULE = "*/15 * * * *"

    def execute(self) -> list[Effect]:
        mappings = list(StaffCalendarMapping.objects.filter(active=True))
        if not mappings:
            return []
        totals = sync_all_blocks(self.secrets, mappings)
        if totals["pushed"] or totals["deleted"]:
            log.info(
                "Block sweep: pushed %s, deleted %s across %s provider(s)",
                totals["pushed"],
                totals["deleted"],
                len(mappings),
            )
        return []
