from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.patient import Patient, SexAtBirth
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

from logger import log


class Protocol(BaseProtocol):
    """
    Displays a banner to let user know the patient sex is not male or female
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PLUGIN_CREATED), # for plugin install
        EventType.Name(EventType.PLUGIN_UPDATED),

        EventType.Name(EventType.PATIENT_CREATED), # for patient created or updated
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    banner_key = "sex-banner"

    def compute(self) -> list[Effect]:

        if self.event.type in (EventType.PLUGIN_UPDATED, EventType.PLUGIN_CREATED):
            patients = Patient.objects.all()
        else:
            patients = Patient.objects.filter(id=self.target)

        effects = []
        for patient in patients:
            log.info(f'Patient {patient.id} sex is {patient.sex_at_birth}')
            if patient.sex_at_birth not in [SexAtBirth.FEMALE.value, SexAtBirth.MALE.value]:
                banner = AddBannerAlert(
                    patient_id=patient.id,
                    key=self.banner_key,
                    narrative=f"WARNING: Patient sex is {patient.sex_at_birth}. EPCS Rx requires a sex of F or M for successful transmission",
                    placement=[AddBannerAlert.Placement.TIMELINE, AddBannerAlert.Placement.CHART, AddBannerAlert.Placement.PROFILE],
                    intent=AddBannerAlert.Intent.ALERT
                )
            else:
                banner = RemoveBannerAlert(
                    key=self.banner_key,
                    patient_id=patient.id,
                )

            effects.append(banner.apply())

        return effects
