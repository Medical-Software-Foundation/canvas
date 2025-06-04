from logger import log
from http import HTTPStatus

from canvas_sdk.events import EventType
from canvas_sdk.effects import Effect
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.v1.data.patient import Patient, PatientContactPoint
from canvas_sdk.handlers.simple_api import Credentials, api, SimpleAPI
from canvas_sdk.effects.simple_api import JSONResponse, Response

BRIDGE_SANDBOX = 'https://app.usebridge.xyz'

class BridgePatientSync(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PATIENT_CONTACT_POINT_CREATED),
        EventType.Name(EventType.PATIENT_CONTACT_POINT_UPDATED),
        # leaving as a TODO for now
        # will need to export PatientAddress as a standalone data model to support these
        # EventType.Name(EventType.PATIENT_ADDRESS_CREATED),
        # EventType.Name(EventType.PATIENT_ADDRESS_UPDATED),
    ]

    @property
    def bridge_api_base_url(self):
        return self.sanitize_url(self.secrets['BRIDGE_API_BASE_URL'] or f'{BRIDGE_SANDBOX}/api')

    @property
    def bridge_ui_base_url(self):
        return self.sanitize_url(self.secrets['BRIDGE_UI_BASE_URL'] or BRIDGE_SANDBOX)

    @property
    def bridge_request_headers(self):
        bridge_secret_api_key = self.secrets['BRIDGE_SECRET_API_KEY']
        return {'X-API-Key': bridge_secret_api_key}

    @property
    def bridge_patient_metadata(self):
        metadata = {
            'canvasPatientId': self.target
        }

        canvas_url = self.secrets['CANVAS_BASE_URL']
        if canvas_url:
            metadata['canvasUrl'] = canvas_url

        return metadata

    def get_patient_id(self):
        if self.event.type in [EventType.PATIENT_CREATED, EventType.PATIENT_UPDATED]:
            return self.target
        elif self.event.type in [EventType.PATIENT_CONTACT_POINT_CREATED, EventType.PATIENT_CONTACT_POINT_UPDATED]:
            contact_point_id = self.target
            if not hasattr(self, '_cached_contact_point') or self._cached_contact_point.id != contact_point_id:
                self._cached_contact_point = PatientContactPoint.objects.get(id=contact_point_id)
            return self._cached_contact_point.patient.id
        # elif self.event.type in [EventType.PATIENT_ADDRESS_CREATED, EventType.PATIENT_ADDRESS_UPDATED]:
        #     address_id = self.target
        #     address = PatientAddress.objects.get(id=address_id)
        #     return address.patient.id

    def compute(self):
        event_type = self.event.type
        canvas_patient_id = self.get_patient_id()
        contact_point_id = self.target if event_type in [EventType.PATIENT_CONTACT_POINT_CREATED, EventType.PATIENT_CONTACT_POINT_UPDATED] else None

        log.info(f'>>> BridgePatientSync.compute {EventType.Name(event_type)} for {canvas_patient_id}')

        http = Http()

        bridge_patient_id = None

        if event_type in [EventType.PATIENT_UPDATED, EventType.PATIENT_CONTACT_POINT_CREATED, EventType.PATIENT_CONTACT_POINT_UPDATED]:
            get_bridge_patient = http.get(
                f'{self.bridge_api_base_url}/patients/v2/{canvas_patient_id}',
                headers=self.bridge_request_headers
            )
            bridge_patient_id = get_bridge_patient.json()['id'] if get_bridge_patient.status_code == 200 else None

        if not bridge_patient_id and event_type in [EventType.PATIENT_UPDATED, EventType.PATIENT_CONTACT_POINT_CREATED, EventType.PATIENT_CONTACT_POINT_UPDATED]:
            log.info('>>> Missing Bridge patient for update; trying create instead')
            event_type = EventType.PATIENT_CREATED

        # Get a reference to the target patient
        canvas_patient = Patient.objects.get(id=canvas_patient_id)
        contact_point = self._cached_contact_point if contact_point_id else None

        # Generate the payload for creating or updating the patient in Bridge
        # At the moment this is just sending a contact point (as telecom) if it is present via the event,
        # regardless of the event type (create or update)
        # And since ContactPoint is referred to elsewhere as 'telecom' I'm assuming it is NOT an email...
        # TODO: Pass email and address here
        bridge_payload = {
            'externalId': canvas_patient.id,
            'firstName': canvas_patient.first_name,
            'lastName': canvas_patient.last_name,
            'dateOfBirth': canvas_patient.birth_date.isoformat(),
            'telecom': contact_point if contact_point else None,
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

        if event_type == EventType.PATIENT_CREATED and resp.status_code == 409:
            log.info(f'>>> Bridge patient already exists for {canvas_patient_id}')
            return []

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

class BridgePatientSyncApi(SimpleAPI):
    # https://<instance-name>.canvasmedical.com/plugin-io/api/bridge-patient-sync/routes/patients
    PATH = "/routes/patients"

    def authenticate(self, credentials: Credentials) -> bool:
        return True

    # https://docs.canvasmedical.com/sdk/handlers-simple-api-http/
    @api.post("/")
    def post(self) -> list[Response | Effect]:
        json_body = self.request.json()
        if not isinstance(json_body, dict):
            return [
                JSONResponse(
                    content="Invalid JSON body.",
                    status_code=HTTPStatus.BAD_REQUEST
                ).apply()
            ]

        patient = Patient.objects.create(
            first_name=json_body.get('firstName'),
            last_name=json_body.get('lastName'),
            birth_date=json_body.get('dateOfBirth'),
        )

        return [
            JSONResponse(
                content=str(patient),
                status_code=HTTPStatus.CREATED).apply()
        ]
