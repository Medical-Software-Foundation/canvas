from logger import log
from http import HTTPStatus

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.effects.patient import Patient as PatientEffect, PatientExternalIdentifier as PatientExternalIdentifierEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.patient import Patient, PatientContactPoint, SexAtBirth
from canvas_sdk.v1.data.common import PersonSex

from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api

BRIDGE_SANDBOX = 'https://app.usebridge.xyz'

class BridgePatientSync(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        # leaving as a TODO for now to focus on the bidirectionality of the sync:
        # EventType.Name(EventType.PATIENT_CONTACT_POINT_CREATED),
        # EventType.Name(EventType.PATIENT_CONTACT_POINT_UPDATED),
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
            'canvasPatientId': self.get_patient_id()
        }

        canvas_url = self.secrets['CANVAS_BASE_URL']
        if canvas_url:
            metadata['canvasUrl'] = canvas_url

        return metadata

    def get_patient_id(self):
        if self.event.type in [EventType.PATIENT_CREATED, EventType.PATIENT_UPDATED]:
            return self.target
        # elif self.event.type in [EventType.PATIENT_ADDRESS_CREATED, EventType.PATIENT_ADDRESS_UPDATED]:
        #     address_id = self.target
        #     address = PatientAddress.objects.get(id=address_id)
        #     return address.patient.id

    def get_system_id(self, canvas_patient, system):
        # If the patient already has a system external identifier, use the first one
        if canvas_patient.external_identifiers.filter(system=system).count() > 0:
            return canvas_patient.external_identifiers(system=system)[0].value

    def system_patient_lookup(self, canvas_patient_id):
        http = Http()
        return http.get(
            f'{self.bridge_api_base_url}/patients/v2/{canvas_patient_id}',
            headers=self.bridge_request_headers
                )

    def compute(self):
        event_type = self.event.type
        canvas_patient_id = self.get_patient_id()

        log.info(f'>>> BridgePatientSync.compute {EventType.Name(event_type)} for {canvas_patient_id}')

        http = Http()

        canvas_patient = Patient.objects.get(id=canvas_patient_id)

        existing_system_id = self.get_system_id(canvas_patient, "Bridge")
        system_patient_id = existing_system_id if existing_system_id else None

        # if it's a patient update, check if external system ID exists and needs to be added to the model
        if event_type in [EventType.PATIENT_UPDATED]:
            if system_patient_id:
                # If the patient already has a third party external identifier in Canvas, use it
                update_patient_external_identifier = False
            else:
                # Get the third party ID by seeing if they exist in third party
                get_system_patient = self.system_patient_lookup(canvas_patient_id)

                system_patient_id = get_system_patient.json()['id'] if get_system_patient.status_code == 200 else None
                update_patient_external_identifier = True if system_patient_id else False

        # Great, now we know if the patient has a third party ID and if we need to update it.
        # At this point it can be 3 values: None, value from Canvas, or value from third party
        # all stored in `system_patient_id` with a bool call to action: `update_patient_external_identifier`

        # If they still don't have a third party ID, they don't exist and we need to create them.
        # So existing plugin says to change the event type. (?)
        if not system_patient_id and event_type in [EventType.PATIENT_UPDATED]:
            log.info('>>> Missing third party patient for update; trying create instead')
            event_type = EventType.PATIENT_CREATED

        # Generate the payload for creating or updating the patient in third party API
        # regardless of the event type (create or update)
        # TODO: Pass contacts and address here
        bridge_payload = {
            'externalId': canvas_patient.id,
            'firstName': canvas_patient.first_name,
            'lastName': canvas_patient.last_name,
            'dateOfBirth': canvas_patient.birth_date.isoformat(),
            # 'telecom': [self.serialize_contact_point(contact_point)] if contact_point else [],
        }

        if event_type == EventType.PATIENT_CREATED:
            # Add placeholder email when creating the Bridge patient since it's required
            bridge_payload['email'] = 'patient_' + canvas_patient.id + '@canvasmedical.com'
            bridge_payload['metadata'] = self.bridge_patient_metadata

        base_request_url = f'{self.bridge_api_base_url}/patients/v2'

        # If we HAVE a Bridge patient id, we know this is an update, so we'll append it to the request URL
        request_url = f'{base_request_url}/{system_patient_id}' if system_patient_id else base_request_url

        log.info(f'>>> Bridge request URL: {request_url}')
        log.info(f'>>> Bridge patient payload: json={bridge_payload}')
        log.info(f'>>> Bridge request headers: headers={self.bridge_request_headers}')

        resp = http.post(
            request_url,
            json=bridge_payload,
            headers=self.bridge_request_headers
        )

        if event_type == EventType.PATIENT_CREATED and resp.status_code == 409:
            log.info(f'>>> Bridge patient already exists for {canvas_patient_id}')
            return []
        elif (update_patient_external_identifier == True):
            # queue up an effect to update the patient in canvas and add the external ID
            log.info(f'>>> Call PatientExternalIdentifierEffect to add system external identifier {system_patient_id} to patient')
            # external_id = PatientExternalIdentifierEffect(
            #     patient_id=canvas_patient.id
            #     system="Bridge"
            #     value=system_patient_id
            # )
            # external_id.create()

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
        log.info(f'>>> Bridge patient data: {bridge_patient_data}')

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
    # https://<instance-name>.canvasmedical.com/plugin-io/api/bridge/patients

    def authenticate(self, credentials: Credentials) -> bool:
        api_key = self.secrets["my_canvas_api_key"]
        log.info(f'BridgePatientSyncApi.post: authenticating with API key {api_key}')

        return True

    # https://docs.canvasmedical.com/sdk/handlers-simple-api-http/
    @api.post("/patients")
    def post(self) -> list[Response | Effect]:
        json_body = self.request.json()
        log.info(f'BridgePatientSyncApi.post: {json_body}')

        if not isinstance(json_body, dict):
            return [
                JSONResponse(
                    content="Invalid JSON body.",
                    status_code=HTTPStatus.BAD_REQUEST
                ).apply()
            ]
        birthdate = None
        date_of_birth_str = json_body.get('dateOfBirth')
        if date_of_birth_str:
            birthdate = arrow.get(date_of_birth_str).date()

        sex_at_birth = None
        sex_at_birth_str = json_body.get('sexAtBirth')
        if sex_at_birth_str:
            s = sex_at_birth_str.strip().upper()
            if s in ("F", "FEMALE"):
                sex_at_birth = PersonSex.SEX_FEMALE
            elif s in ("M", "MALE"):
                sex_at_birth = PersonSex.SEX_MALE
            elif s in ("O", "OTHER"):
                sex_at_birth = PersonSex.SEX_OTHER
            elif s in ("U", "UNKNOWN"):
                sex_at_birth = PersonSex.SEX_UNKNOWN
            else:
                sex_at_birth = None

        # this supports the first external identifier but could be extended to support multiple
        external_id = PatientExternalIdentifierEffect(
            system=str(json_body.get('externalIdentifiers', [{}])[0].get('system', 'Bridge')),
            value=str(json_body.get('externalIdentifiers', [{}])[0].get('id', '')),
            issued_date=arrow.now().datetime,
            expiration_date=arrow.now().datetime.add(years=10).datetime
        )

        patient = PatientEffect(
            birthdate=birthdate,
            first_name=str(json_body.get('firstName')),
            last_name=str(json_body.get('lastName')),
            sex_at_birth=sex_at_birth,
            external_identifiers=[external_id],
        )
        log.info(f'BridgePatientSyncApi.post: patient={patient}')

        return [patient.create(),
            JSONResponse(
                content=str(patient),
                status_code=HTTPStatus.CREATED).apply()
        ]
