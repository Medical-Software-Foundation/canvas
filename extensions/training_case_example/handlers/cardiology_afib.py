from time import sleep

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data import Staff
from extensions.training_case_example.handlers.api_clients import NoteAPIClient
from canvas_sdk.commands import ReasonForVisitCommand, HistoryOfPresentIllnessCommand

from logger import log


class AfibCase(BaseProtocol):
    RESPONDS_TO = [EventType.Name(EventType.PATIENT_CREATED)]

    def compute(self) -> list[Effect]:
        log.info(f'self.target: {self.target}')
        log.info(f'self.context: {self.context}')
        
        staff = Staff.objects.filter(active=True).exclude(npi_number='').order_by('created').last()
        log.info(f'staff: {staff}')
        
        # Create the Note using the Note API
        note_client = NoteAPIClient(self.secrets['CLIENT_ID'], self.secrets['CLIENT_SECRET'], 'xpc-dev')
        response = note_client.create_encounter(self.target, staff.id)
        log.info(response.status_code)
        log.info(response.text)
        resp_json = response.json()
        note_id = resp_json['noteKey']
        
        # Fill it out using command classes
        
        rfv = ReasonForVisitCommand(
            note_uuid=note_id, 
            comment='Feeling dizzy, heart palpitations, very concerned')
        
        hpi = HistoryOfPresentIllnessCommand(
            note_uuid=note_id,
            narrative='Patient reports 5 days of worsening fatigue and dizziness. <more>')
        
        # TODO: Add other chart data, e.g. external reports, past notes, etc

        return [rfv.originate(), hpi.originate()]
