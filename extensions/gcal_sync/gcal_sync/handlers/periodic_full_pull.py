"""Re-checks each provider's whole Google calendar window about once a day.

Delta pulls only return what Google reports as changed, so an event a delta never delivered stays
missing from Canvas. This cron full-pulls a couple of calendars per tick, oldest full pull first,
without reviving holds staff cancelled. It is a cheap no-op when every calendar is current.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from gcal_sync.reconcile import periodic_full_pull


class PeriodicFullPullCron(CronTask):
    """Full-pulls the calendars whose last full pull is more than a day old, a few per run."""

    SCHEDULE = "*/10 * * * *"

    def execute(self) -> list[Effect]:
        _totals, effects = periodic_full_pull(self.secrets)
        return effects
