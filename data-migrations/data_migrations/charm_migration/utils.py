from urllib.parse import urlencode
import random, string

import requests
from decouple import Config, RepositoryIni
from data_migrations.utils import fetch_from_json, write_to_json


class APIException(Exception):
    pass

class APIMethodMixin:
    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.auth.access_token}",
            "api_key": self.auth.charm_api_key
        }

    def get_request(self, url, params=None):
        response = requests.get(
            url,
            headers=self.headers,
            params=params if params else {}
        )
        return response


class CharmAPIAuth:
    def __init__(self, scopes, environment) -> None:
        ini = RepositoryIni('../config.ini')
        ini.SECTION = environment
        config = Config(ini)

        self.charm_client_id = config("charm_client_id", cast=str)
        self.charm_client_secret = config("charm_client_secret", cast=str)
        self.charm_api_key = config("charm_api_key", cast=str)
        self.charm_patient_api_refresh_token = config("charm_patient_api_refresh_token", cast=str)

        self.scopes = scopes
        self.base_auth_url = "https://accounts.charmtracker.com"
        self.access_token = None

    def get_authorization_grant_url(self):
        params = {
            "scope": ",".join(self.scopes),
            "client_id": self.charm_client_id,
            "state": ''.join(random.choice(string.ascii_letters + string.digits) for i in range(16)),
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": "https://ehr2.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON"
        }
        url_params = urlencode(params)
        return f"{self.base_auth_url}/oauth/v2/auth?{url_params}"

    def get_refresh_token(self, code):
        params = {
            "code": code,
            "client_id": self.charm_client_id,
            "client_secret": self.charm_client_secret,
            "redirect_uri": "https://ehr2.charmtracker.com/ehr/physician/mySpace.do?ACTION=SHOW_OAUTH_JSON",
            "grant_type": "authorization_code"
        }

        response = requests.post(
            "https://accounts.charmtracker.com/oauth/v2/token",
            headers={"Content-Type": "application/json"},
            params=params
        )
        return response

    def get_access_token_with_refresh_token(self, refresh_token):
        params = {
            "refresh_token": refresh_token,
            "client_id": self.charm_client_id,
            "client_secret": self.charm_client_secret,
            "grant_type": "refresh_token",
        }

        response = requests.post(
            f"{self.base_auth_url}/oauth/v2/token",
            headers={"Content-Type": "application/json"},
            params=params
        )
        return response.json()["access_token"]

    def sign_in(self):
        sign_in_url = self.get_authorization_grant_url()
        print(sign_in_url)

        print("Sign in to the URL and then enter the code here")
        acquired_code = input("code: ")

        refresh_token_response = self.get_refresh_token(acquired_code)
        self.access_token = refresh_token_response.json()["access_token"]
        print(refresh_token_response.json())


class CharmPatientAPI(APIMethodMixin):
    PATIENT_API_SCOPES = [
        "charmhealth.patient.allergy.READ",
        "charmhealth.patient.careteam.READ",
        "charmhealth.patient.ccda.READ",
        "charmhealth.patient.chartnote.READ",
        "charmhealth.patient.demographics.READ",
        "charmhealth.patient.document.READ",
        "charmhealth.patient.fullaccess.READ",
        "charmhealth.patient.immunization.READ",
        "charmhealth.patient.implant.READ",
        "charmhealth.patient.injection.READ",
        "charmhealth.patient.labresult.READ",
        "charmhealth.patient.medication.READ",
        "charmhealth.patient.problem.READ",
        "charmhealth.patient.medicalhistory.READ",
        "charmhealth.patient.procedure.READ",
        "charmhealth.patient.referral.READ",
        "charmhealth.patient.sticky.READ",
        "charmhealth.patient.supplement.READ",
        "charmhealth.patient.vital.READ",
        "charmhealth.user.calendar.READ",
        "charmhealth.user.message.READ",
        "charmhealth.user.setting.facility.READ",
        "charmhealth.user.setting.member.READ",
        "charmhealth.user.setting.questionnaire.READ",
        "charmhealth.user.setting.READ",
        "charmhealth.user.task.READ",
        "charmhealth.user.template.READ",
        "system/Patient.read",
        "user/Patient.read"
    ]

    def __init__(self, environment):
        self.base_patient_api_url = "https://ehr2.charmtracker.com"
        self.auth = CharmAPIAuth(scopes=self.PATIENT_API_SCOPES, environment=environment)
        # refresh access token for the patient API
        self.refresh_access_token()

    def refresh_access_token(self):
        self.auth.access_token = self.auth.get_access_token_with_refresh_token(self.auth.charm_patient_api_refresh_token)

    def get(self, uri, params=None):
        # The auth times out quickly, so let's refresh the token if we don't get a 200 on the first try
        for number_try in range(2):
            response = self.get_request(f"{self.base_patient_api_url}{uri}", params=params)
            if response.status_code == 200:
                return response
            elif number_try == 0:
                print("Refreshing the access_token")
                self.refresh_access_token()
            else:
                raise APIException(f"Status {response.status_code}: {str(response.content)}")

    def fetch_patients(self):
        patient_list = []
        patient_endpoint = "/api/ehr/v1/patients"
        has_next_page = True
        page = 1

        while has_next_page is True:
            params = {
                "facility_id": "ALL",
                "page": page,
                "sort_order": "A",
                "sort_column": "record_id",
                "per_page": 100
            }
            print(f"Fetching patients page {page}")
            patient_response = self.get(patient_endpoint, params=params)
            patient_json = patient_response.json()
            patient_list.extend(patient_json['patients'])
            if patient_json['page_context']['has_more_page'] == 'true':
                page = page + 1
            else:
                has_next_page = False

        return patient_list
