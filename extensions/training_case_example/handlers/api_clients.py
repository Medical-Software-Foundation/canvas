import requests
from canvas_sdk.utils import Http
from requests import Response
from datetime import datetime, timezone, timedelta
from logger import log
from canvas_sdk.v1.data import PracticeLocation

class NoteAPIClient:
    def __init__(self, client_id, client_secret, subdomain):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = f"https://{subdomain}.canvasmedical.com/"
        self.token = self.get_token()

    def get_token(self) -> Response:
        url = self.base_url + "auth/token/"
        payload = f'grant_type=client_credentials&client_id={self.client_id}&client_secret={self.client_secret}'
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(url, headers=headers, data=payload)
        json_resp = response.json()
        return json_resp["access_token"]

    def create_encounter(self, patient_id, practitioner_id):
        url = self.base_url + 'core/api/notes/v1/Note'
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        location_id = str(PracticeLocation.objects.filter(active=True).first().id)
        start_time = datetime.now(timezone.utc)
        formatted_start_time = start_time.strftime("%Y-%m-%dT%H:%M:00.000Z")
        payload = {
            'patientKey': patient_id,
            'providerKey': practitioner_id,
            'practiceLocationKey': location_id,
            'noteTypeName': 'Office visit',
            'encounterStartTime': formatted_start_time
        }
        log.info(headers)
        log.info(payload)
        return requests.post(url, headers=headers, json=payload)


class FHIRClient:
    def __init__(self, base_url, api_key):
        self
        self.base_url = base_url.rstrip('/') + '/'
        self.headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json"
        }

    def create_appointment(self, patient_id: str, practitioner_id: str, start_time=None, duration=None) -> Response:
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        formatted_start_time = start_time.strftime("%Y-%m-%dT%H:%M:00.000Z")
        formatted_end_time = (start_time + timedelta(minutes=duration or 20)).strftime("%Y-%m-%dT%H:%M:00.000Z")
        location_id = str(PracticeLocation.objects.filter(active=True).first().id)
        resource = 'Appointment'
        reason_for_visit_comment = 'Feeling dizzy, heart palpitations, very concerned'
        url = self.base_url + resource

        payload = {
            "resourceType": resource,
            "status": "checked-in",
            "appointmentType":
            {
                "coding":
                [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "308335008",
                        "display": "Office visit"
                    }
                ]
            },
            # TODO: implement RFV as command after note is created
            "reasonCode":
            [
                {
                    # "coding":
                    # [
                    #     {
                    #         "system": "CUSTOM",
                    #         "code": "10101",
                    #         "display": "Welcome Visit",
                    #         "userSelected": False
                    #     }
                    # ],
                    "text": reason_for_visit_comment
                }
            ],
            "supportingInformation":
            [
                {
                    "reference": f"Location/{location_id}"
                }
            ],
            "start": formatted_start_time,
            "end": formatted_end_time,
            "participant":
            [
                {
                    "actor":
                    {
                        "reference": f"Patient/{patient_id}"
                    },
                    "status": "accepted"
                },
                {
                    "actor":
                    {
                        "reference": f"Practitioner/{practitioner_id}"
                    },
                    "status": "accepted"
                }
            ]
        }

        return requests.post(url, json=payload, headers=self.headers)
