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
        self.charm_fhir_api_refresh_token = config("charm_fhir_api_refresh_token", cast=str)

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

    def fetch_allergies(self, patient_ids):
        allergy_list = []
        allergy_endpoint = "/api/ehr/v1/patients/{patient_id}/allergies"

        for patient_id in patient_ids:
            has_next_page = True
            page = 1
            print(f"Fetching allergies for patient ID {patient_id}")

            while has_next_page is True:
                params = {
                    "page": page,
                    "sort_order": "A",
                    "per_page": 100
                }
                allergy_response = self.get(allergy_endpoint.format(patient_id=patient_id), params=params)
                allergy_json = allergy_response.json()
                allergy_list.extend(allergy_json['allergies'])
                if allergy_json['page_context']['has_more_page'] == 'true':
                    page = page + 1
                else:
                    has_next_page = False
        return allergy_list

    def fetch_medications(self, patient_ids):
        medication_list = []
        medication_endpoint = "/api/ehr/v1/patients/{patient_id}/medications"

        for patient_id in patient_ids:
            has_next_page = True
            page = 1
            print(f"Fetching medications for patient ID {patient_id}")

            while has_next_page is True:
                params = {
                    "page": page,
                    "sort_order": "A",
                    "per_page": 100
                }
                medication_response = self.get(medication_endpoint.format(patient_id=patient_id), params=params)
                medication_json = medication_response.json()
                medication_list.extend(medication_json['medications'])
                if medication_json['page_context']['has_more_page'] == 'true':
                    page = page + 1
                else:
                    has_next_page = False
        return medication_list

    def fetch_supplements(self, patient_ids):
        supplement_list = []
        supplement_endpoint = "/api/ehr/v1/patients/{patient_id}/supplements"

        for patient_id in patient_ids:
            has_next_page = True
            page = 1
            print(f"Fetching supplements for patient ID {patient_id}")

            while has_next_page is True:
                params = {
                    "page": page,
                    "sort_order": "A",
                    "per_page": 100
                }
                supplement_response = self.get(supplement_endpoint.format(patient_id=patient_id), params=params)
                supplement_json = supplement_response.json()
                supplement_list.extend(supplement_json['supplements'])
                if supplement_json['page_context']['has_more_page'] == 'true':
                    page = page + 1
                else:
                    has_next_page = False
        return supplement_list

    def fetch_diagnoses(self, patient_ids):
        diagnoses_list = []
        diagnoses_endpoint = "/api/ehr/v1/patients/{patient_id}/diagnoses"

        for patient_id in patient_ids:
            print(f"Fetching diagnoses for patient ID {patient_id}")
            diagnoses_response = self.get(diagnoses_endpoint.format(patient_id=patient_id))
            diagnoses_json = diagnoses_response.json()
            # we need to add the patient ID as a key because it is not in each record
            # there is also no pagination for this endpoint, it gives all the diagnoses per patient
            diagnoses_list.append({"patient_id": patient_id, "diagnoses": diagnoses_json['patient_diagnoses']})
        return diagnoses_list

    def fetch_questionnaire_answers(self, patient_ids, file_path):
        patient_questionnaires = fetch_from_json(file_path)
        questionnaire_endpoint = "/api/ehr/v1/patients/{patient_id}/questionnaires"
        questionnaire_map_endpoint = "/api/ehr/v1/questionnaire/answer/{ques_map_id}"
        patient_count = 0
        for patient_id in patient_ids:
            patient_count += 1
            if patient_id in patient_questionnaires or patient_id == "337879000202123319" or patient_id == "337879000238405343": # this one seems to give a 500
                # already written to file
                continue
            print(f"Fetching questionnaires for patient ID {patient_id} - {patient_count} of {len(patient_ids)}")
            has_next_page = True
            page = 1
            patient_questionnaire_list = []
            while has_next_page is True:
                params = {"page": str(page)}
                response = self.get(questionnaire_endpoint.format(patient_id=patient_id), params=params)
                response_data = response.json()
                for question_map in response_data["patient_questionnaires"]:
                    question_map_response = self.get(questionnaire_map_endpoint.format(ques_map_id=question_map["ques_map_id"]))
                    question_map_data = question_map_response.json()
                    question_map["questionnaire_with_answers"] = question_map_data["questionnaire_with_answers"]
                    patient_questionnaire_list.append(question_map)
                if response_data['page_context']['has_more_page'] == 'true':
                    page = page + 1
                else:
                    has_next_page = False
            patient_questionnaires[patient_id] = patient_questionnaire_list
            if patient_count % 100 == 0:
                write_to_json(file_path, patient_questionnaires)
        write_to_json(file_path, patient_questionnaires)


    def fetch_questionnaires(self):
        questionnaire_data = []
        questionnaire_endpoint = "/api/ehr/v1/questionnaires"
        has_next_page = True
        page = 1
        while has_next_page is True:
            params = {"page": str(page)}
            response = self.get(questionnaire_endpoint, params=params)
            response_data = response.json()
            questionnaire_data.extend(response_data["questionnaires"])
            if response_data['page_context']['has_more_page'] == 'true':
                page = page + 1
            else:
                has_next_page = False
        return questionnaire_data

    def fetch_questionnaire_questions(self, questionnaire_ids):
        questionnaire_questions = {}
        questionnaire_endpoint = "/api/ehr/v1/questionnaire/{questionnaire_id}"
        for q_id in questionnaire_ids:
            print(f"Fetching questionnaire questions for questionnaire id {q_id}")
            response = self.get(questionnaire_endpoint.format(questionnaire_id=q_id))
            response_data = response.json()
            questionnaire_questions[q_id] = response_data["data"]
        return questionnaire_questions

    def fetch_vaccines(self, patient_ids):
        vaccine_endpoint = "/api/ehr/v1/patients/{patient_id}/vaccines"
        vaccine_read_endpoint = "/api/ehr/v1/patients/{patient_id}/vaccines/{patient_vaccine_id}"
        vaccine_list = []
        for patient_id in patient_ids:
            has_next_page = True
            while has_next_page is True:
                print(f"Fetching vaccines for patient id {patient_id}")
                vaccine_response = self.get(vaccine_endpoint.format(patient_id=patient_id))
                vaccine_json = vaccine_response.json()
                if vaccine_json['vaccines']:
                    for vaccine in vaccine_json['vaccines']:
                        vaccine_list_obj = vaccine
                        # there is more info that we need with a read
                        vaccine_detail = self.get(vaccine_read_endpoint.format(patient_id=patient_id, patient_vaccine_id=vaccine["patient_vaccine_map_id"]))
                        vaccine_list_obj["detail"] = vaccine_detail
                        vaccine_list.append(vaccine_list_obj)
                if vaccine_json['page_context']['has_more_page'] == 'true':
                    page = page + 1
                else:
                    has_next_page = False
        return vaccine_list

    def fetch_vitals(self, patient_ids):
        vitals = []
        vitals_endpoint = "/api/ehr/v1/patients/{patient_id}/vitals"
        for patient_id in patient_ids:
            print(f"Fetching vitals for patient {patient_id}")
            vitals_response = self.get(vitals_endpoint.format(patient_id=patient_id))
            vitals_json = vitals_response.json()
            if vitals_json["vital_entries"]:
                vitals_dict = {"patient_id": patient_id, "vitals": vitals_response.json()["vital_entries"]}
                vitals.append(vitals_dict)
        return vitals

    def fetch_lab_results(self):
        lab_results = []
        labs_endpoint = "/api/ehr/v1/labs/results"
        has_next_page = True
        start_index = 1
        no_of_records = 50 # looks like the max

        while has_next_page is True:
            params = {"sort_by": "DATE", "is_ascending": True, "start_index": start_index, "no_of_records": no_of_records}
            print(f"Fetching lab results start index {start_index}")
            lab_response = self.get(labs_endpoint, params=params)
            labs_json = lab_response.json()
            lab_results.extend(labs_json["lab_results"])
            if labs_json["page_context"]["has_more_page"] == True:
                start_index += no_of_records
            else:
                has_next_page = False
        return lab_results

    def fetch_lab_file(self, pdf_url):
        print(f"Retrieving lab result file {pdf_url}")
        return self.get(pdf_url)

    def fetch_expanded_lab_results(self, group_ids):
        # Returns a dict with group ID->expanded result
        expanded_results = {}
        lab_result_url = "/api/ehr/v1/labs/results/{group_id}"
        for group_id in group_ids:
            print(f"Fetching expanded lab result with group ID {group_id}")
            response = self.get(
                lab_result_url.format(group_id=group_id)
            )
            lab_data = response.json()
            expanded_results[group_id] = lab_data
        return expanded_results

    def fetch_messages(self, patient_ids, file_path):
        patient_messages = fetch_from_json(file_path)
        messages_endpoint = "/api/ehr/v1/messages/patient/{patient_id}"
        message_details_endpoint = "/api/ehr/v1/messages/{message_id}"
        patient_count = 0
        for patient_id in patient_ids:
            patient_count += 1
            if patient_id in patient_messages:
                continue
            patient_cnt_msg = f"{patient_count} of {len(patient_ids)} patients"
            print(f"Fetching messages for patient id {patient_id} - {patient_cnt_msg}")
            for direction in ["sent", "received"]:
                messages = []
                page = 1
                has_next_page = True
                print(f"Fetching details for {direction} messages")
                while has_next_page is True:
                    message_response = self.get(
                        messages_endpoint.format(patient_id=patient_id),
                        params={"section": direction, "sort_order": "A", "page": page}
                    )
                    response_data = message_response.json()
                    for msg in response_data["messages"]:
                        print(f"Fetching details for {direction} message ID {msg["message_id"]}: {patient_cnt_msg} - patient id {patient_id}")
                        msg_details = self.get(
                            message_details_endpoint.format(message_id=msg["message_id"])
                        )
                        msg_details_data = msg_details.json()
                        msg["message_details"] = msg_details_data
                        messages.append(msg)
                    if response_data["page_context"]["has_more_page"] == "true":
                        page += 1
                    else:
                        has_next_page = False
                if patient_id not in patient_messages:
                    patient_messages[patient_id] = {direction: messages}
                else:
                    patient_messages[patient_id][direction] = messages
            if patient_count % 100 == 0:
                print("Writing to file")
                write_to_json(file_path, patient_messages)
        write_to_json(file_path, patient_messages)

    def fetch_quicknotes(self, patient_ids):
        quicknotes = {}
        quicknotes_endpoint = "/api/ehr/v1/patients/{patient_id}/quicknotes"
        patient_len = len(patient_ids)
        patient_num = 1
        for patient_id in patient_ids:
            patient_quicknotes = []
            print(f"Fetching quicknotes for patient id {patient_id} - {patient_num} of {patient_len}")
            page = 1
            has_next_page = True
            while has_next_page is True:
                params = {"page": page, "per_page": 50}
                quicknotes_response = self.get(
                    quicknotes_endpoint.format(patient_id=patient_id),
                    params=params
                )
                quicknotes_data = quicknotes_response.json()
                patient_quicknotes.extend(quicknotes_data["quick_notes"])
                if quicknotes_data["page_context"]["has_more_page"] == "true":
                    page += 1
                else:
                    has_next_page = False
            if patient_quicknotes:
                quicknotes[patient_id] = patient_quicknotes
            patient_num += 1
        return quicknotes

    def fetch_documents(self, patient_ids, json_file, files_dir):
        documents = fetch_from_json(json_file)
        documents_endpoint = "/api/ehr/v1/patients/{patient_id}/documents"
        patient_count = 0
        for patient_id in patient_ids:
            patient_count += 1
            if patient_id in documents:
                continue
            print(f"Fetching documents for patient id {patient_id} - {patient_count} of {len(patient_ids)}")
            patient_documents = []
            has_next_page = True
            page = 1
            while has_next_page is True:
                params = {"page": page}
                response = self.get(documents_endpoint.format(patient_id=patient_id), params=params)
                document_data = response.json()
                patient_documents.extend(document_data["documents"])

                if document_data["page_context"]["has_more_page"] == "true":
                    page += 1
                else:
                    has_next_page = False
            documents[patient_id] = patient_documents

            # don't download all the documents to disk;
            # just fetch them during each import and then delete;
            # file_id = doc_info["file_id"]
            # print(f"Fetching file id {file_id}")
            # document_response = self.get(f"/api/ehr/v1/patients/{patient_id}/documents/{file_id}/file")
            # with open(f"{files_dir}{file_id}.pdf", "wb") as fhandle:
            #    fhandle.write(document_response.content)
            if patient_count % 500 == 0:
                write_to_json(json_file, documents)
        write_to_json(json_file, documents)

    def fetch_file(self, patient_id, file_id):
        print(f"Fetching file id {file_id}")
        document_response = self.get(f"/api/ehr/v1/patients/{patient_id}/documents/{file_id}/file")
        return document_response.content

    def read_encounter(self, encounter_id):
        encounter_endpoint = "/api/ehr/v1/encounters/{encounter_id}"
        return self.get(
            encounter_endpoint.format(encounter_id=encounter_id)
        )


class CharmFHIRAPI(APIMethodMixin):
    FHIR_API_SCOPES = [
        "system/AllergyIntolerance.read",
        "system/Appointment.read",
        "system/CarePlan.read",
        "system/CareTeam.read",
        "system/Condition.read",
        "system/Device.read",
        "system/DiagnosticReport.read",
        "system/DocumentReference.read",
        "system/Encounter.read",
        "system/FamilyMemberHistory.read",
        "system/Goal.read",
        "system/Immunization.read",
        "system/Location.read",
        "system/MedicationAdministration.read",
        "system/MedicationRequest.read",
        "system/Observation.read",
        "system/Organization.read",
        "system/Patient.read",
        "system/Practitioner.read",
        "system/Procedure.read",
        "system/Provenance.read",
        "system/QuestionnaireResponse.read",
        "system/RelatedPerson.read",
        "user/AllergyIntolerance.read",
        "user/Appointment.read",
        "user/CarePlan.read",
        "user/CareTeam.read",
        "user/Condition.read",
        "user/Device.read",
        "user/DiagnosticReport.read",
        "user/DocumentReference.read",
        "user/Encounter.read",
        "user/FamilyMemberHistory.read",
        "user/Goal.read",
        "user/Immunization.read",
        "user/Location.read",
        "user/MedicationAdministration.read",
        "user/MedicationRequest.read",
        "user/Observation.read",
        "user/Organization.read",
        "user/Patient.read",
        "user/Practitioner.read",
        "user/Procedure.read",
        "user/Provenance.read",
        "user/QuestionnaireResponse.read",
        "user/RelatedPerson.read",
        "user/Medication.read",
        "offline_access"
    ]

    def __init__(self, environment):
        self.base_fhir_api_url = "https://ehr2.charmtracker.com/api/ehr/v2/fhir"
        self.auth = CharmAPIAuth(scopes=self.FHIR_API_SCOPES, environment=environment)
        self.refresh_access_token()

    def refresh_access_token(self):
        self.auth.access_token = self.auth.get_access_token_with_refresh_token(self.auth.charm_fhir_api_refresh_token)

    def response_has_next_page(self, response_json):
        next_links = [bool(r.get("relation") == "next" and r.get("url")) for r in response_json.get("link", [])]
        print(response_json.get("link", []))
        print(next_links)
        return any(next_links)

    def get(self, uri, params=None):
        # TODO - make this shared in the APIMethodMixin
        # The auth times out quickly, so let's refresh the token if we don't get a 200 on the first try
        for number_try in range(2):
            response = self.get_request(f"{self.base_fhir_api_url}{uri}", params=params)
            if response.status_code == 200:
                return response
            elif response.status_code == 404:
                raise APIException(f"Status {response.status_code}: {str(response.content)}")
            elif number_try == 0:
                print("Refreshing the access_token")
                self.refresh_access_token()
            else:
                raise APIException(f"Status {response.status_code}: {str(response.content)}")

    def fetch_allergies(self):
        allergy_list = []
        has_next_page = True
        page = 1

        while has_next_page is True:
            params = {
                "clinical-status": "active",
                "page": str(page)
            }
            print(f"Fetching allergies page {page}")
            allergy_response = self.get(
                f"/AllergyIntolerance",
                params=params
            )
            response_data = allergy_response.json()
            allergy_list.extend(response_data["entry"])

            if not self.response_has_next_page(response_data):
                has_next_page = False
            else:
                page += 1
        return allergy_list


    def fetch_medication_requests(self):
        medication_list = []
        has_next_page = True
        page = 1

        while has_next_page is True:
            params = {"page": str(page)}
            print(f"Fetching MedicationRequest page {page}")
            medication_response = self.get(
                f"/MedicationRequest",
                params=params
            )
            response_data = medication_response.json()
            medication_list.extend(response_data["entry"])

            if not self.response_has_next_page(response_data):
                has_next_page = False
            else:
                page += 1
        return medication_list

    def fetch_medication_entries(self, medication_ids):
        # Fetches the actual drug info - not patient specific
        # https://www.charmhealth.com/resources/fhir/index.html#get-medication
        medication_list = []
        for medication_id in medication_ids:
            print(f"Fetching Medication ID {medication_id}")
            medication = self.get(f"/Medication/{medication_id}")
            response_data = medication.json()
            medication_list.append(response_data)
        return medication_list

    def fetch_diagnostic_lab_reports(self):
        diagnostic_report_list = []
        has_next_page = True
        page = 1
        while has_next_page is True:
            params = {"page": str(page), "category": "LAB"}
            print(f"Fetching Diagnostic Reports page {page}")
            response = self.get("/DiagnosticReport", params=params)
            response_data = response.json()

            diagnostic_report_list.extend(response_data["entry"])

            if not self.response_has_next_page(response_data):
                has_next_page = False
            else:
                page += 1
        return diagnostic_report_list

    def get_practitioners(self):
        practitioner_list = []
        has_next_page = True
        page = 1
        while has_next_page is True:
            params = {"page": str(page)}
            print(f"Fetching Practitioners page {page}")
            response = self.get("/Practitioner", params=params)
            response_data = response.json()

            practitioner_list.extend(response_data["entry"])

            if not self.response_has_next_page(response_data):
                has_next_page = False
            else:
                page += 1
        return practitioner_list
