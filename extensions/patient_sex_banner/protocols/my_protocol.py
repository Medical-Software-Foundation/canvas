from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.patient import Patient, SexAtBirth
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

from logger import log


class Protocol(BaseProtocol):
    """Banner-alert a patient whose sex at birth is not Male or Female.

    Subscribes only to per-patient events, so each event reconciles a single
    patient. Plugin lifecycle events are deliberately not subscribed: iterating
    every patient on install/update produces an unbounded, instance-wide effect
    batch. Backfilling existing patients belongs in a deliberate, paged job.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    banner_key = "sex-banner"

    def compute(self) -> list[Effect]:
        try:
            patient = Patient.objects.get(id=self.target)
        except Patient.DoesNotExist:
            return []

        log.info(f"Patient {patient.id} sex is {patient.sex_at_birth}")

        if patient.sex_at_birth not in (SexAtBirth.FEMALE.value, SexAtBirth.MALE.value):
            banner = AddBannerAlert(
                patient_id=patient.id,
                key=self.banner_key,
                narrative=f"WARNING: Patient sex is {patient.sex_at_birth}. EPCS Rx requires a sex of F or M for successful transmission",
                placement=[
                    AddBannerAlert.Placement.TIMELINE,
                    AddBannerAlert.Placement.CHART,
                    AddBannerAlert.Placement.PROFILE,
                ],
                intent=AddBannerAlert.Intent.ALERT,
            )
        else:
            banner = RemoveBannerAlert(
                key=self.banner_key,
                patient_id=patient.id,
            )

        return [banner.apply()]
