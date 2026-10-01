"""Scheduled job that makes, moves, and closes the automatic failed-fax tasks."""

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from failed_fax_dashboard.services.alerts import alert_effects


class FaxAlertCron(CronTask):
    """Every 5 minutes, find failed faxes the job hasn't handled and keep their tasks current."""

    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        """Return the task effects for new failures and newly delivered faxes."""
        return alert_effects(self.secrets, self.environment)
