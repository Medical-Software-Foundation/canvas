import json
import requests
import arrow

from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.protocol import (STATUS_NOT_APPLICABLE,
                                          ClinicalQualityMeasure,
                                          ProtocolResult)
from canvas_workflow_kit.utils import send_notification
from canvas_workflow_kit.internal.integration_messages import create_task_payload
from canvas_workflow_kit.fhir import FumageHelper

class PrescriptionErrorTaskCreator(ClinicalQualityMeasure):
    class Meta:

        title = 'Prescription error task creator'
        version = '1.0.0'
        description = 'Listens for prescription errors and creates a task.'
        types = ['Notification']
        compute_on_change_types = [CHANGE_TYPE.PRESCRIPTION]
        notification_only = True

    def get_fhir_medicationrequest(self, prescription_id):
        """ Read FHIR MedicationRequest using prescription ID"""
        fhir = FumageHelper(self.settings)
        response = fhir.read("MedicationRequest", prescription_id)

        if response.status_code != 200:
            raise Exception("Failed to search MedicationRequest")

        return response.json()

    def compute_results(self):
        result = ProtocolResult()

        # Get the name of the prescription
        prescription_id = self.field_changes.get('external_id')
        if prescription_id:
            sdk_prescription = self.patient.prescriptions.filter(externallyExposableId=prescription_id).records

            if sdk_prescription:
                prescription_name = sdk_prescription[0]['coding'][0].get('display')
                for d in sdk_prescription[0]['coding']:
                    if d.get('system') == 'http://www.fdbhealth.com/':
                        prescription_name = d.get('display')

                # Get the prescriber key
                fhir_medrequest = self.get_fhir_medicationrequest(prescription_id)
                requester_key = fhir_medrequest['requester']['reference'].split('/')[1]

                # Create a task if the prescription error-ed
                status_change = self.field_changes.get('fields').get('status')

                if status_change and status_change[1] == 'error':
                    title = f"Prescription for {prescription_name} encountered an error."
                    now = arrow.now().isoformat()
                    task_payload = create_task_payload(
                        patient_key=self.patient.patient['key'],
                        created_by_key=requester_key,
                        status="OPEN",
                        title=title,
                        assignee_identifier=requester_key,
                        due=now,
                        created=now,
                        tag=None,
                        labels=[],
                    )
                    result.add_narrative(f"Task was created with title: {title}")
                    self.set_updates([task_payload])

        return result
