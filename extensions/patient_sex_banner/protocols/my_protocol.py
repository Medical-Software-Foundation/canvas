from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.patient import Patient

from logger import log
from patient_sex_banner.banner import banner_effect_for_patient


class Protocol(BaseProtocol):
    """Banner-alert a patient whose sex at birth is not Male or Female.

    Subscribes only to per-patient events, so each event reconciles a single
    patient. Plugin lifecycle events are deliberately not subscribed: iterating
    every patient on install/update produces an unbounded, instance-wide effect
    batch. Existing patients are backfilled by BackfillBanners, a paged cron task.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    def compute(self) -> list[Effect]:
        try:
            patient = Patient.objects.get(id=self.target)
        except Patient.DoesNotExist:
            return []

        log.info(f"Patient {patient.id} sex is {patient.sex_at_birth}")
        return [banner_effect_for_patient(patient)]
