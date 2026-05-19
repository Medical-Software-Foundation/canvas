"""Emit a banner alert when a patient chart loads, gated by ACCESS_SHOW_BANNER secret."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from cms_access_fhir_client.models import ACCESSAlignment


class AccessBannerHandler(BaseHandler):
    """Show the patient's current ACCESS alignment status in the chart banner."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def compute(self) -> list[Effect]:
        if self.secrets.get("ACCESS_SHOW_BANNER", "").lower() != "true":
            return []

        patient_id = self.event.target.id
        alignment = (
            ACCESSAlignment.objects.filter(patient__id=patient_id)
            .order_by("-updated_at")
            .first()
        )

        if not alignment:
            return []

        status = alignment.status
        track = alignment.track

        if status == ACCESSAlignment.STATUS_ALIGNED:
            narrative = f"ACCESS aligned — {track}"
            intent = AddBannerAlert.Intent.INFO
        elif status == ACCESSAlignment.STATUS_PENDING:
            narrative = f"ACCESS enrollment pending — {track}"
            intent = AddBannerAlert.Intent.WARNING
        elif status in (ACCESSAlignment.STATUS_UNALIGNED, ACCESSAlignment.STATUS_ERROR):
            narrative = f"ACCESS not enrolled (status: {status})"
            intent = AddBannerAlert.Intent.WARNING
        else:
            # eligible, ineligible, already-aligned — surface but don't alarm
            narrative = f"ACCESS status: {status}"
            intent = AddBannerAlert.Intent.INFO

        return [
            AddBannerAlert(
                patient_id=patient_id,
                key="access-alignment-status",
                narrative=narrative[:90],
                placement=[AddBannerAlert.Placement.CHART],
                intent=intent,
            ).apply()
        ]
