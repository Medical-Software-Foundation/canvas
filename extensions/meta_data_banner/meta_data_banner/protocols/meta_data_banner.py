from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.patient import Patient

from meta_data_banner.banner import banner_effect_for_patient


class MetaDataBanner(BaseHandler):
    """Surfaces patient metadata as a banner alert on the chart summary.

    Responds to per-patient metadata events and reconciles that single
    patient's banner in real time. The full-panel backfill/refresh is handled
    separately by MetaDataBannerBackfill (a paged cron task) so plugin
    lifecycle events never trigger an instance-wide scan.

    The BANNER_TEMPLATE secret defines the banner text. Use {metadata_key}
    placeholders to insert patient metadata values.

    Example: "Care Program: {ccm_diagnosis}" will replace {ccm_diagnosis}
    with the patient's ccm_diagnosis metadata value.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_METADATA_CREATED),
        EventType.Name(EventType.PATIENT_METADATA_UPDATED),
    ]

    def compute(self):
        template = self.secrets.get("BANNER_TEMPLATE", "")
        if not template:
            return []

        patient_id = self.context["patient"]["id"]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return []

        return [banner_effect_for_patient(patient, template)]
