import random
from logger import log
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.effects.protocol_card import ProtocolCard, Recommendation
from canvas_sdk.v1.data.patient import Patient


class BridgePatientSync(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED)
        ]

    def compute(self):
        log.info('>>> BridgePatientSync.compute')
        
        bridge_api_base_url = self.secrets['BRIDGE_API_BASE_URL']
        bridge_secret_api_key = self.secrets['BRIDGE_SECRET_API_KEY']
        
        patient = Patient.objects.get(id=self.target)

        # TODO: pass phone, email if available (Canvas doesn't require)
        bridge_payload = {
            "firstName": patient.first_name,
            "lastName": patient.last_name,
            "email": 'test_' + str(random.random())[2:] + '@canvasmedical.com',
            "dateOfBirth": patient.birth_date.isoformat()
        }
            
        if bridge_api_base_url[-1] != '/':
            bridge_api_base_url += '/'
        
        http = Http()
        resp = http.post(
            bridge_api_base_url + 'patients/',
            headers={"X-API-Key": bridge_secret_api_key})

        log.info(f'>>> resp.status_code: {resp.status_code} ')
        log.info(f'>>> resp.text: {resp.text} ')
        try:
            log.info(f'>>> resp.json(): {resp.json()} ')
        except Exception as e:
            log.info(f'>>> resp.json resulted in error {e}')

        # TODO display bridge patient url as button in protocol card
        p = ProtocolCard(
            patient_id=self.target,
            key="bridge-patient-link",
            title="Link to Patient in Bridge",
            narrative="This patient is automatically sync'd from Canvas to Bridge.",
            recommendations=[]
        )

        # TODO: construct href from post response (assuming patient identifier included)
        p.add_recommendation(
            title="", button="Bridge Patient", href="https://app.usebridge.xyz/patients/pat_TTKgod72yXIIdaW7"
        )

        # TODO: how to store Canvas patient url in Bridge for backlinking?
        # TODO: is it enough to store Bridge patient url in protocol card?
        # TODO: better to get into `externally exposable id` field?

        return [p.apply()]
