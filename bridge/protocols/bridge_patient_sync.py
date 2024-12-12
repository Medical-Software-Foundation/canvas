from logger import log
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.v1.data.patient import Patient


class BridgePatientSync(BaseProtocol):
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
        return self.sanitize_url(self.secrets['BRIDGE_API_BASE_URL'])

    @property
    def bridge_ui_base_url(self):
        return self.sanitize_url(self.secrets['BRIDGE_UI_BASE_URL'])

    @property
    def bridge_request_headers(self):
        bridge_secret_api_key = self.secrets['BRIDGE_SECRET_API_KEY']
        return {'X-API-Key': bridge_secret_api_key}

    def compute(self):
        canvas_patient_id = self.target
        event_type = self.event.type
        log.info(f'>>> BridgePatientSync.compute {event_type} for {canvas_patient_id}')

        http = Http()
        log.info('>>> Fetching Bridge patient')
        get_bridge_patient = http.get(
            f'{self.bridge_api_base_url}/patients/{canvas_patient_id}',
            headers=self.bridge_request_headers
        )
        log.info(f'>>> Received response with status {get_bridge_patient.status_code}')

        bridge_patient_id = None
        if get_bridge_patient.status_code == 200:
            log.info(f'>>> Found Bridge patient with id {bridge_patient_id}')
            bridge_patient_id = get_bridge_patient.json()['id']
        
        if bridge_patient_id and event_type == EventType.PATIENT_CREATED:
            log.info(f'>>> Skipping create patient; Bridge patient already exists')
            return []
        
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
        
        base_request_url = f'{self.bridge_api_base_url}/patients'
        # If we have a Bridge patient id, we know this is an update, so we'll append it to the request URL
        request_url = f'{base_request_url}/{bridge_patient_id}' if bridge_patient_id else base_request_url

        # Create or update the patient in Bridge
        resp = http.post(
            request_url,
            json=bridge_payload,
            headers=self.bridge_request_headers
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

        # TODO: is it enough to store Bridge patient url in banner alert?
        # TODO: better to get into `externally exposable id` field?
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

        return [sync_banner.apply()]
    
    def sanitize_url(self, url):
        # Remove a trailing forward slash since our request paths will start with '/'
        return url[:-1] if url[-1] == '/' else url
