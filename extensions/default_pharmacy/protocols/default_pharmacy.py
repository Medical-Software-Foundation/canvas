import requests

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol


class PatientFHIRException(Exception):
    pass


class DefaultPharmacyProtocol(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_COMMIT),
        EventType.Name(EventType.REFILL_COMMAND__POST_COMMIT),
    ]

    FHIR_PHARMACY_EXTENSION = "http://schemas.canvasmedical.com/fhir/extensions/preferred-pharmacy"

    @property
    def fhir_host(self):
        environment = self.environment["CUSTOMER_IDENTIFIER"]
        return f"https://fumage-{environment}.canvasmedical.com"

    def get_fhir_patient(self, patient_id):
        patient_response = requests.get(
            f"{self.fhir_host}/Patient/{patient_id}",
            headers={"Authorization": f"Bearer {self.secrets['BEARER_TOKEN']}"},
        )
        if patient_response.status_code != 200:
            raise PatientFHIRException(
                f"{patient_response.status_code} - {str(patient_response.content)}"
            )
        return patient_response.json()

    def update_fhir_patient(self, patient_id, payload):
        patient_update = requests.put(
            f"{self.fhir_host}/Patient/{patient_id}",
            json=payload,
            headers={"Authorization": f"Bearer {self.secrets['BEARER_TOKEN']}"},
        )
        if patient_update.status_code != 200:
            raise PatientFHIRException(
                f"{patient_update.status_code} - {str(patient_update.content)}"
            )

    def preferred_pharmacy_extension(self, command_pharmacy, default_pharmacy=True):
        extension = {
            "extension": [
                {
                    "url": "ncpdp-id",
                    "valueIdentifier": {
                        "system": "http://terminology.hl7.org/CodeSystem/NCPDPProviderIdentificationNumber",
                        "value": command_pharmacy["extra"]["ncpdp_id"],
                    },
                }
            ],
            "url": self.FHIR_PHARMACY_EXTENSION,
        }
        if default_pharmacy is True:
            extension["extension"].append({"url": "default", "valueBoolean": True})
        return extension

    def compute(self) -> list[Effect]:
        patient_id = self.event.context["patient"]["id"]
        pharmacy = self.event.context["fields"]["pharmacy"]

        if pharmacy:
            fhir_patient = self.get_fhir_patient(patient_id)
            command_pharmacy_id = pharmacy.get("extra", {}).get("ncpdp_id")

            if command_pharmacy_id:
                default_pharmacy_ncpdp_id = None
                patient_pharmacy_ncpdp_ids = {}

                for ext_idx, extension in enumerate(fhir_patient.get("extension", [])):
                    if extension.get("url") == self.FHIR_PHARMACY_EXTENSION:
                        is_default = bool(
                            list(
                                filter(
                                    lambda x: x.get("url") == "default"
                                    and x.get("valueBoolean") == True,
                                    extension.get("extension", []),
                                )
                            )
                        )
                        ncpdp_id = [
                            e["valueIdentifier"]["value"]
                            for e in extension["extension"]
                            if e.get("url") == "ncpdp-id"
                        ][0]
                        patient_pharmacy_ncpdp_ids[ncpdp_id] = ext_idx
                        if is_default:
                            default_pharmacy_ncpdp_id = ncpdp_id

                # Patient does not have a default pharmacy and the selected pharmacy is
                # not currently a patient preferred pharmacy. Add it via FHIR.
                if (
                    not default_pharmacy_ncpdp_id
                    and command_pharmacy_id not in patient_pharmacy_ncpdp_ids
                ):
                    pharmacy_extension = self.preferred_pharmacy_extension(pharmacy)
                    fhir_patient["extension"].append(pharmacy_extension)
                    self.update_fhir_patient(patient_id, fhir_patient)

                # Patient has a default pharmacy that is different than the selected pharmacy.
                elif (
                    default_pharmacy_ncpdp_id
                    and default_pharmacy_ncpdp_id != command_pharmacy_id
                ):
                    # Remove the default flag from the current default pharmacy
                    fhir_patient["extension"][
                        patient_pharmacy_ncpdp_ids[default_pharmacy_ncpdp_id]
                    ]["extension"] = list(
                        filter(
                            lambda x: not (
                                x.get("url") == "default"
                                and x.get("valueBoolean") == True
                            ),
                            fhir_patient["extension"][
                                patient_pharmacy_ncpdp_ids[default_pharmacy_ncpdp_id]
                            ]["extension"],
                        )
                    )

                    # Selected pharmacy is already a preferred pharmacy. Add the default flag to the new one.
                    if command_pharmacy_id in patient_pharmacy_ncpdp_ids:
                        fhir_patient["extension"][
                            patient_pharmacy_ncpdp_ids[command_pharmacy_id]
                        ]["extension"].append({"url": "default", "valueBoolean": True})
                        self.update_fhir_patient(patient_id, fhir_patient)

                    # Selected pharmacy is not a preferred pharmacy - add it and have it a set as the default.
                    else:
                        preferred_pharmacy_extension = (
                            self.preferred_pharmacy_extension(pharmacy)
                        )
                        fhir_patient["extension"].append(preferred_pharmacy_extension)
                        self.update_fhir_patient(patient_id, fhir_patient)
        return []
