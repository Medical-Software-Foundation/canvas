from logger import log
from typing import Any

from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.effects.patient import CreatePatientExternalIdentifier
from canvas_sdk.v1.data.patient import Patient

BRIDGE_SANDBOX = "https://app.usebridge.xyz"

class BridgePatientSync(BaseProtocol):
    """Syncs patient data between Canvas and Bridge when created/updated in Canvas."""

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),

        # TODO: Support the below once we figure out how to get the patient from
        #       the target ID (these events have self.target = entity.id where
        #       entity may be a telecom or address)
        # EventType.Name(EventType.PATIENT_CONTACT_POINT_CREATED),
        # EventType.Name(EventType.PATIENT_CONTACT_POINT_UPDATED),
        # EventType.Name(EventType.PATIENT_ADDRESS_CREATED),
        # EventType.Name(EventType.PATIENT_ADDRESS_UPDATED),
    ]

    @property
    def bridge_api_base_url(self):
        """Returns the base URL for the Bridge API."""
        return self.sanitize_url(self.secrets['BRIDGE_API_BASE_URL'] or f'{BRIDGE_SANDBOX}/api')

    @property
    def bridge_ui_base_url(self):
        """Returns the base URL for the Bridge UI."""
        return self.sanitize_url(self.secrets['BRIDGE_UI_BASE_URL'] or BRIDGE_SANDBOX)

    @property
    def bridge_request_headers(self) -> dict[str, str]:
        bridge_secret_api_key = self.secrets['BRIDGE_SECRET_API_KEY']
        return {'X-API-Key': bridge_secret_api_key}

    @property
    def bridge_patient_metadata(self):
        """Returns metadata for the Bridge patient."""

        metadata = {
            'canvasPatientId': self.target
        }

        canvas_url = self.secrets['CANVAS_BASE_URL']
        if canvas_url:
            # This sets the canvas URL for the patient in the Bridge platform metadata, e.g. "https://training.canvasmedical.com"
            # Combined with the canvasPatientId, this allows the Bridge platform to link back to the patient in Canvas
            metadata['canvasUrl'] = canvas_url

        return metadata

    def lookup_external_id_by_bridge_url(self, canvas_patient: Patient, system: str) -> str | None:
        """Get the Bridge ID for a given patient in Canvas."""
        # If the patient already has a external identifier for the Bridge platform, identified by a matching system url, use the first one
        return (
            canvas_patient.external_identifiers.filter(system=system)
            .values_list("value", flat=True)
            .first()
        )

    def get_patient_from_bridge_api(self, canvas_patient_id: str) -> Any:
        """Look up a patient in the Bridge API."""
        http = Http()
        return http.get(
            f"{self.bridge_api_base_url}/patients/v2/{canvas_patient_id}",
            headers=self.bridge_request_headers,
        )

    def compute(self) -> list[Effect]:
        """Compute the sync actions for the patient."""

        canvas_patient_id = self.target
        event_type = self.event.type
        log.info(f'>>> BridgePatientSync.compute {EventType.Name(event_type)} for {canvas_patient_id}')

        http = Http()

        canvas_patient = Patient.objects.get(id=canvas_patient_id)
        # by default assume we don't yet have a system patient ID
        # and that we need to update the patient in Canvas to add one
        system_patient_id = self.lookup_external_id_by_bridge_url(canvas_patient, BRIDGE_SANDBOX)
        update_patient_external_identifier = system_patient_id is None

        # Here we check if the patient already has an external ID in Canvas for the partner platform
        if not system_patient_id:
            log.info(f">>> No external ID found for Canvas Patient ID {canvas_patient_id}:")

            # Get the system external ID by making a GET request to the partner platform
            system_patient = self.get_patient_from_bridge_api(canvas_patient_id)

            system_patient_id = (
                system_patient.json()["id"] if system_patient.status_code == 200 else None
            )
            log.info(
                f">>>System patient ID for Canvas Patient ID {canvas_patient_id} is {system_patient_id}"
            )
            log.info(f">>> Need to update patient? {update_patient_external_identifier}")

        # Great, now we know if the patient is assigned a system external ID with the partner
        # platform, and if we need to update it. At this point the system_patient_id can be 3 values:
        # 1. value we already had stored in Canvas,
        # 2. value we just got from our GET API lookup, or
        # 3. None
        # And we have a true/false call to action: `update_patient_external_identifier`

        bridge_patient_id = system_patient_id
        if event_type == EventType.PATIENT_UPDATED:
            get_bridge_patient = http.get(
                f'{self.bridge_api_base_url}/patients/v2/{canvas_patient_id}',
                headers=self.bridge_request_headers
            )
            bridge_patient_id = get_bridge_patient.json()['id'] if get_bridge_patient.status_code == 200 else None

        if not bridge_patient_id and event_type == EventType.PATIENT_UPDATED:
            log.info('>>> Missing Bridge patient for update; trying create instead')
            event_type = EventType.PATIENT_CREATED

        # Get a reference to the target patient
        canvas_patient = Patient.objects.get(id=canvas_patient_id)

        # Generate the payload for creating or updating the patient in Bridge
        # TODO: Pass phone, email, and address here
        bridge_payload = {
            'externalId': canvas_patient.id,
            'firstName': canvas_patient.first_name,
            'lastName': canvas_patient.last_name,
            'dateOfBirth': canvas_patient.birth_date.isoformat(),
        }

        if event_type == EventType.PATIENT_CREATED:
            # Add placeholder email when creating the Bridge patient since it's required
            bridge_payload['email'] = 'patient_' + canvas_patient.id + '@canvasmedical.com'
            bridge_payload['metadata'] = self.bridge_patient_metadata

        base_request_url = f'{self.bridge_api_base_url}/patients/v2'
        # If we have a Bridge patient id, we know this is an update, so we'll append it to the request URL
        request_url = f'{base_request_url}/{bridge_patient_id}' if bridge_patient_id else base_request_url

        # Create or update the patient in Bridge
        resp = http.post(
            request_url,
            json=bridge_payload,
            headers=self.bridge_request_headers
        )

        log.info(f">>> Partner platform API request URL: {request_url}")
        log.info(f">>> Partner platform API patient payload: json={bridge_payload}")
        log.info(
            f">>> Partner platform API request headers: headers={self.bridge_request_headers}"
        )

        # If the request was successful, we should now have a system patient ID if we didn't before
        if bridge_patient_id is None:
            bridge_patient_id = resp.json().get("id")

        external_id = None
        if event_type == EventType.PATIENT_CREATED and resp.status_code == 409:
            log.info(f'>>> Bridge patient already exists for {canvas_patient_id}')
            return []
        elif update_patient_external_identifier:
            # queue up an effect to update the patient in canvas and add the external ID
            external_id = CreatePatientExternalIdentifier(
                patient_id=canvas_patient.id,
                system=BRIDGE_SANDBOX,
                value=str(bridge_patient_id)
            )

        # If the post is unsuccessful, notify end users
        # TODO: implement workflow to remedy this,
        # TODO: e.g. end user manually completes a questionnaire with the Bridge link?
        if resp.status_code != 200:
            log.error(f'bridge-patient-sync FAILED with status {resp.status_code}')
            log.info(resp.text)
            sync_warning = AddBannerAlert(
                patient_id=canvas_patient.id,
                key='bridge-patient-sync',
                narrative='No link to patient in Bridge',
                placement=[
                    AddBannerAlert.Placement.CHART,
                    AddBannerAlert.Placement.APPOINTMENT_CARD,
                    AddBannerAlert.Placement.SCHEDULING_CARD,
                    AddBannerAlert.Placement.PROFILE
                ],
                intent=AddBannerAlert.Intent.WARNING
            )
            return [sync_warning.apply()]

        # Otherwise, get the resulting patient info and build the link to Bridge
        bridge_patient_data = resp.json()
        sync_banner = AddBannerAlert(
            patient_id=canvas_patient.id,
            key='bridge-patient-sync',
            narrative='View patient in Bridge',
            placement=[
                AddBannerAlert.Placement.CHART,
                AddBannerAlert.Placement.APPOINTMENT_CARD,
                AddBannerAlert.Placement.SCHEDULING_CARD,
                AddBannerAlert.Placement.PROFILE
            ],
            intent=AddBannerAlert.Intent.INFO,
            href=f"{self.bridge_ui_base_url}/patients/{bridge_patient_data['id']}"
        )

        effects = []
        if external_id is not None:
            effects.append(external_id.create())
        effects.append(sync_banner.apply())
        return effects

    def sanitize_url(self, url):
        # Remove a trailing forward slash since our request paths will start with '/'
        return url[:-1] if url[-1] == '/' else url
