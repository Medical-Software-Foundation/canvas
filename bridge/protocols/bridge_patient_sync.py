import random
from logger import log
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.v1.data.patient import Patient


class BridgePatientSync(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED)
        ]

    CREATION_LOCKS = set()

    def compute(self):
        log.info('>>> BridgePatientSync.compute')
        
        bridge_ui_base_url = self.secrets['BRIDGE_UI_BASE_URL']
        bridge_api_base_url = self.secrets['BRIDGE_API_BASE_URL']
        bridge_secret_api_key = self.secrets['BRIDGE_SECRET_API_KEY']
        
        if bridge_api_base_url[-1] != '/':
            bridge_api_base_url += '/'
        
        
        if bridge_ui_base_url[-1] != '/':
            bridge_ui_base_url += '/'
        
        # Get a reference to the target patient
        canvas_patient = Patient.objects.get(id=self.target)

        # Ensure not invoked more than once
        if canvas_patient.id in BridgePatientSync.CREATION_LOCKS:
            log.info('>>> Aborted due to BridgePatientSync.CREATION_LOCKS')
            return []
        else:
            BridgePatientSync.CREATION_LOCKS.add(canvas_patient.id)

        # TODO: pass phone, email if available (Canvas doesn't require email)
        bridge_payload = {
            "externalId": canvas_patient.id,
            "firstName": canvas_patient.first_name,
            "lastName": canvas_patient.last_name,
            "email": 'patient_' + canvas_patient.id + '@canvasmedical.com',
            "dateOfBirth": canvas_patient.birth_date.isoformat()
        }
        
        # Create the patient in Bridge
        # TODO: Check for or otherwise manage duplicates?
        http = Http()
        resp = http.post(
            bridge_api_base_url + 'patients/', json=bridge_payload,
            headers={"X-API-Key": bridge_secret_api_key})

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
            href=f"{bridge_ui_base_url}patients/{bridge_patient_data['id']}"
        )

        return [sync_banner.apply()]
