import json
import http
from time import sleep

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data import Staff, Appointment, Note
from training_case_example.handlers.fhir_client import FHIRClient
from canvas_sdk.commands import HistoryOfPresentIllnessCommand

from logger import log


class AfibCase(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_CREATED),
    ]

    def compute(self) -> list[Effect]:
        if self.event.type == EventType.PATIENT_CREATED:
            return self.add_encounter()
        if self.event.type == EventType.APPOINTMENT_CREATED:
            return self.write_note()
        # TODO: Add external reports
        patient_id = self.event.target.id

    def add_encounter(self):
        log.info(f'self.target: {self.target}')
        log.info(f'self.context: {self.context}')
        staff = Staff.objects.filter(active=True).exclude(npi_number='').order_by('created').last()
        log.info(f'staff: {staff}')
        fhir = FHIRClient(self.secrets['FHIR_BASE_URL'], self.secrets['FHIR_API_KEY'])
        sleep(3)
        response = fhir.create_appointment(self.target, staff.id)
        log.info(response.status_code)
        log.info(response.text)
        log.info(response.headers)
        return []

    def write_note(self):
        note = Appointment.objects.get(id=self.target).note
        hpi = HistoryOfPresentIllnessCommand(
            note_uuid=str(note.id),
            narrative='Patient reports 5 days of worsening fatigue and dizziness. <more>')

        # TODO: write more of the note with more commands...

        return [hpi.originate()]
