from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import CreatePatientPreferredPharmacies, PatientPreferredPharmacy
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol

from logger import log


class DefaultPharmacyProtocol(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.REFILL_COMMAND__POST_COMMIT),
    ]


    def compute(self) -> list[Effect]:
        patient_id = self.event.context["patient"]["id"]
        pharmacy = self.event.context["fields"]["pharmacy"]
        pharmacy_ncpdp_id = pharmacy["extra"]["ncpdp_id"]

        log.info(f"Updating preferred pharmacy to NCPDP id {pharmacy_ncpdp_id}")

        preferred_pharmacy_effect = CreatePatientPreferredPharmacies(
            pharmacies=[PatientPreferredPharmacy(ncpdp_id=pharmacy_ncpdp_id, default=True)],
            patient_id=patient_id
        )

        return [preferred_pharmacy_effect.create()]
