from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import RemoveBannerAlert
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.banner_alert import BannerAlert


class RemoveStatusBanners(CronTask):
    SCHEDULE = "0 0 * * *"  # Run at 00:00.

    def execute(self) -> list[Effect]:
        effects = []
        open_banner_alerts = BannerAlert.objects.filter(key="rooming-status", status="active")
        for banner_alert in open_banner_alerts:
            remove_banner = RemoveBannerAlert(
                key='rooming-status',
                patient_id=banner_alert.patient.id,
            )
            effects.append(remove_banner.apply())

        return effects
