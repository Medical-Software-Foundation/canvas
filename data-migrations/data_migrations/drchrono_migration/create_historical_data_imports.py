import sys, datetime, requests, json, csv, arrow, base64, io, os
from pprint import pprint
from collections import defaultdict
from utils import DrChronoHelper
from customer_migrations.utils import fetch_from_csv, fetch_complete_csv_rows, fetch_from_json, load_fhir_settings

class DataImportLoader:
    """
        During a historical Data Migration, at Canvas we create a historical data note to store a patient's
        allergies, problems, medications, and vaccines all in one place.
    """

    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = 'PHI/note_map.csv'
        self.finished_patient_file = 'results/patients_finished.csv'

        self.done_allergies_file = 'results/done_allergies.csv'
        self.done_medications_file = 'results/done_medications.csv'
        self.done_problems_file = 'results/done_problems.csv'
        self.done_vaccines_file = 'results/done_vaccines.csv'

        self.errored_allergies_file = 'results/errored_allergies.csv'
        self.errored_medications_file = 'results/errored_medications.csv'
        self.errored_problems_file = 'results/errored_problems.csv'
        self.errored_vaccines_file = 'results/errored_vaccines.csv'

        self.allergies_file = 'PHI/allergies.csv'
        self.problems_file = 'PHI/problems.csv'
        self.medications_file = 'PHI/medications.csv'
        self.vaccines_file = 'PHI/patient_vaccine_records.csv'

        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map = fetch_from_csv(self.note_map_file)
        self.finished_patient_ids = fetch_complete_csv_rows(self.finished_patient_file, 'dr_chrono_id')
        self.done_allergies = fetch_complete_csv_rows(self.done_allergies_file)
        self.done_medications = fetch_complete_csv_rows(self.done_medications_file)
        self.done_problems = fetch_complete_csv_rows(self.done_problems_file)
        self.done_vaccines = fetch_complete_csv_rows(self.done_vaccines_file)

        # These variables help create access tokens to both Canvas and DrChrono APIs
        self.environment = environment
        self.fumage_helper = load_fhir_settings(self.environment)
        self.fumage_helper.get_fhir_api_token()
        self.drchrono_helper = DrChronoHelper(self.environment)

    def create_medication_coding_map(self, filename, data, fhir_resource, ignore_func=None):

        if os.path.isfile(filename):
            return fetch_from_json(filename)

        _map = {}

        for _, rows in data.items():
            for row in rows:
                print()
                code = row['rxnorm']
                name = row['name'].lower()
                key = f'{code}|{name}'

                if (ignore_func and ignore_func(row)) or key in _map:
                    continue

                name_list = name.split(' ')
                found_coding = None
                for i in reversed(range(len(name_list))):
                    text = " ".join(name_list[:i+1]).strip()
                    if text:
                        search_parameters = {
                            '_text': " ".join(name_list[:i+1])
                        }

                        response = self.fumage_helper.search(fhir_resource, search_parameters)
                        if response.status_code != 200:
                            raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

                        response_json = response.json()
                        if response_json.get('total') == 1:
                            coding = response_json['entry'][0]['resource']['code']['coding']
                            if any([c['code'] == code for c in coding if c['system'] == 'http://www.nlm.nih.gov/research/umls/rxnorm']):
                                found_coding = coding
                                break

                if found_coding:
                    _map[key] = coding
                    print(f"{key} - {_map[key]}")
                    continue

                if code:
                    search_parameters = {
                        'code': f'http://www.nlm.nih.gov/research/umls/rxnorm|{code}'
                    }

                    response = self.fumage_helper.search(fhir_resource, search_parameters)

                    if response.status_code != 200:
                        raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

                    response_json = response.json()
                    if response_json.get('total') == 1:
                        _map[key] = response_json['entry'][0]['resource']['code']['coding']
                    elif response_json.get('total') != 0:
                        found = False
                        for entry in response_json['entry']:
                            coding = entry['resource']['code']['coding']
                            if coding[0]['display'].split(' ')[0].lower() == name_list[0]:
                                _map[key] = coding
                                found = True
                                break
                        if not found:
                            _map[key] = response_json['entry']
                    else:
                        _map[key] = []
                        # print(f"looking up {fhir_resource} row {row['id']} with coding {code} resulted in {response_json}")

                print(f"{key} - {_map.get(key)}")
                print()
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(_map, f, ensure_ascii=False, indent=4)

        return _map

    def create_allergy_coding_map(self, filename, data, fhir_resource, ignore_func=None):

        _map = {}
        if os.path.isfile(filename):
            return fetch_from_json(filename)

        def _perform_fhir_search(search_parameters, key, _mapping):
            response = self.fumage_helper.search(fhir_resource, search_parameters)
            print(f'Performing {response.url}')
            if response.status_code != 200:
                raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

            response_json = response.json()
            if response_json.get('total') == 1:
                _map[key] = response_json['entry'][0]['resource']['code']['coding']
            elif response_json.get('total') != 0:
                _map[key] = response_json['entry']
            else:
                _map[key] = []

            return _map

        for _, rows in data.items():
            for row in rows:
                code = row['rxnorm']

                if ignore_func and ignore_func(row):
                    continue

                if code and code not in _map:
                    search_parameters = {
                        'code': f'http://www.nlm.nih.gov/research/umls/rxnorm|{code}'
                    }
                    _map = _perform_fhir_search(search_parameters, code, _map)

                if not code:
                    # fetch the description of the allergy
                    text = row.get('description')
                    if text:
                        text = text.split(':')[-1].strip()
                        if text not in _map:
                            search_parameters = {'_text': text}
                            _map = _perform_fhir_search(search_parameters, text, _map)

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(_map, f, ensure_ascii=False, indent=4)

        return _map

    def create_vaccine_coding_map(self, filename, data):
        if os.path.isfile(filename):
            return fetch_from_json(filename)

        unique_map = []

        for _, rows in data.items():
            for row in rows:
                item = {'cvx_code': row['cvx_code'], 'cpt_code': row['cpt_code'], 'name': row['name']}
                if item not in unique_map:
                    unique_map.append(item)

        print(unique_map)
        return

        # since there is no FHIR Vaccine Endpoint to validate the codings, we need to run this code against ontologies manually
        # by an engineer
        from api.services.ontologies_service import OntologiesService
        import urllib
        ontologies_service = OntologiesService()
        vaccine_map = {}
        for coding in unique_map:
            print(f"\n\n{coding}\n")

            coding_responses = []
            for key, code_name in [('cvx_code', 'cvx_code'), ('name_or_code', 'cpt_code')]:
                if coding[code_name]:
                    url_encoded_params = urllib.parse.urlencode({key: coding[code_name]})
                    response = ontologies_service.get("/cpt/immunization/", params=url_encoded_params)
                    for r in response['results']:
                        if r not in coding_responses:
                            coding_responses.append(r)

            match = next((c for c in coding_responses if c['cpt_code'] == coding['cpt_code'] and c['cvx_code'] == coding['cvx_code']), None)

            if match:
                vaccine_map["|".join(coding.values())] = [match]
            else:
                vaccine_map["|".join(coding.values())] = coding_responses


        with open('vaccine_coding_map.csv', 'w') as output:
            output.write("cvx_code|cpt_code|name|found|responses\n")
            for key, mappings in vaccine_map.items():
                cvx_code, cpt_code, name = key.split('|')
                found = None
                if len(cpt_code) != 5 or any(not i.isdigit() for i in cpt_code):
                    found = 'n/a'
                if len(mappings) == 1:
                    found = found or (mappings[0]['cpt_code'] == cpt_code and mappings[0]['cvx_code'] == cvx_code)
                    output.write(f"{cvx_code}|{cpt_code}|{name}|{found}|{mappings[0]}\n")
                else:
                    output.write(f"{cvx_code}|{cpt_code}|{name}|{found or False}|{'|'.join(str(m) for m in mappings)}\n")

        # upload to s3
        file = 'vaccine_coding_map.csv'
        from django.core.files.storage import default_storage
        with open(file, "rb") as read_file:
            default_storage.save(file, read_file)

        # with open('vaccine_coding_map.json', 'w', encoding='utf-8') as f:
        #     json.dump(vaccine_map, f, ensure_ascii=False, indent=4)

    def get_or_create_historical_data_input_note(self, canvas_patient_key, drchrono_patient_id):
        if drchrono_patient_id in self.note_map:
            return self.note_map[drchrono_patient_id][0]['note_key']

        payload = {
          "noteTypeName": "DrChrono Data Migration",
          "patientKey": canvas_patient_key,
          "providerKey": "5eede137ecfe4124b8b773040e33be14", # canvas bot key
          "encounterStartTime": "2024-03-01T13:00:00.016852Z"
        }

        base_url = f"https://{self.environment}.canvasmedical.com/core/api/notes/v1/Note"
        response = requests.request("POST", base_url, headers=self.fumage_helper.headers, data=json.dumps(payload))

        if response.status_code != 201:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

        response_json = response.json()
        note_key = response_json['noteKey']

        with open(self.note_map_file, 'a') as note_map:
            note_map.write(f"{drchrono_patient_id}|{canvas_patient_key}|{note_key}\n")

        self.note_map[canvas_patient_key] = [{"patient": drchrono_patient_id, 'patient_key': canvas_patient_key, 'note_key': note_key}]

        return note_key

    def make_sure_note_is_unlocked(self, note_key):
        payload = {
          "stateChange": "ULK"
        }

        # make a GET request to see what the state is now
        base_url = f"https://{self.environment}.canvasmedical.com/core/api/notes/v1/Note/{note_key}"
        response = requests.request("GET", base_url, headers=self.fumage_helper.headers)

        if response.status_code != 200:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

        if response.json()['currentState'] == 'ULK':
            return

        response = requests.request("PATCH", base_url, headers=self.fumage_helper.headers, data=json.dumps(payload))
        if response.status_code != 200:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

    def lock_note(self, note_key):

        payload = {
          "stateChange": "LKD"
        }

        base_url = f"https://{self.environment}.canvasmedical.com/core/api/notes/v1/Note/{note_key}"
        response = requests.request("PATCH", base_url, headers=self.fumage_helper.headers, data=json.dumps(payload))

        if response.status_code != 200 and "LKD -> LKD" not in response.text:
            print(f"Failed to perform {response.url}. \n {response.text}")

        return note_key

    def ingest_allergies(self, patient_key, note_key, patients_allergies):

        print(f'      Found {len(patients_allergies)} allergies')
        for allergy in patients_allergies:
            if allergy['id'] in self.done_allergies:
                continue

            description = allergy['description'].split(':')[-1].strip()

            if not allergy['rxnorm'] and not description:
                with open(self.errored_allergies_file, 'a') as errored_allergies:
                    errored_allergies.write(f"{allergy['id']}|{allergy['patient']}|{patient_key}|||Ignored\n")
                continue # ignore all rows that dont have at least a coding or description

            coding_found = []
            if allergy['rxnorm'] and allergy['rxnorm'] in self.allergen_map:
                coding_found = self.allergen_map.get(allergy['rxnorm'], [])
            elif description and description in self.allergen_map:
                coding_found = self.allergen_map.get(description, [])

            fdb_codes = [coding for coding in coding_found if coding['system'] == 'http://www.fdbhealth.com/']

            if not fdb_codes:
                with open(self.errored_allergies_file, 'a') as errored_allergies:
                    errored_allergies.write(f"{allergy['id']}|{allergy['patient']}|{patient_key}|{allergy['rxnorm']}|{description}||No coding found\n")
                continue # do not create an allergy that we couldn't map to FDB

            for fdb_code in fdb_codes:

                payload = {
                    "resourceType": "AllergyIntolerance",
                    "extension": [
                        {
                            "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                            "valueId": note_key,
                        }
                    ],
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                "code": allergy['status']
                            }
                        ],
                    },
                    "verificationStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                                "code": "confirmed",
                                "display": "Confirmed"
                            }
                        ],
                        "text": "Confirmed"
                    },
                    "type": "allergy",
                    "code": {
                        "coding": [fdb_code]
                    },
                    "patient": {
                        "reference": f"Patient/{patient_key}"
                    },
                    "note": (
                        ([{"text": allergy['description']}] if fdb_code['code'] == "1-143" else []) +
                        ([{"text": allergy['reaction']}] if allergy['reaction'] else []) +
                        ([{"text": f"Notes: allergy['notes']"}] if allergy['notes'] else [])
                    )
                }

                # print(json.dumps(payload, indent=2))
                try:
                    canvas_id = self.fumage_helper.perform_create(payload, note_key)
                    with open(self.done_allergies_file, 'a') as done_allergies:
                        done_allergies.write(f"{allergy['id']}|{allergy['patient']}|{patient_key}|{canvas_id}|{fdb_code['code']}\n")
                    self.done_allergies.add(allergy['id'])
                except BaseException as e:
                    e = str(e).replace('\n', '')
                    with open(self.errored_allergies_file, 'a') as errored_allergies:
                        errored_allergies.write(f"{allergy['id']}|{allergy['patient']}|{patient_key}|{allergy['rxnorm']}|{description}|{fdb_code['code']}|{e}\n")

    def ingest_medications(self, patient_key, note_key, patients_medications):

        print(f'      Found {len(patients_medications)} medications')
        for medication in patients_medications:
            if medication['id'] in self.done_medications:
                continue

            payload = {
                "resourceType": "MedicationStatement",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_key,
                    }
                ],
                "status": "stopped" if medication['date_stopped_taking'] or medication['status'] == 'inactive' else "active",
                "subject": {
                    "reference": f"Patient/{patient_key}"
                },
                "dosage": ([
                    {
                        "text": medication['signature_note']
                    }
                ] if medication['signature_note'] else [])
            }

            mapping_key = f"{medication['rxnorm']}|{medication['name']}".lower()
            found_code = self.medication_map.get(mapping_key)
            if found_code:
                if type(found_code) == str:
                    found_code = eval(found_code)
                code = next(item['code'] for item in found_code if item["system"] == 'http://www.fdbhealth.com/')
                payload["medicationReference"] = {
                    "reference": f"Medication/fdb-{code}",
                }
            elif medication['ndc'] and medication['ndc'] != '0':
                payload["medicationCodeableConcept"] =  {"coding": [
                    {
                        "system": "http://hl7.org/fhir/sid/ndc",
                        "code": medication['ndc'],
                        "display": medication['name']
                    }
                ]}
            else:
                payload["medicationCodeableConcept"] =  {"coding": [
                    {
                        "system": "unstructured",
                        "code": "N/A",
                        "display": medication['name'] or medication['signature_note'] or medication['notes']
                    }
                ]}

            # print(json.dumps(payload, indent=2))
            try:
                canvas_id = self.fumage_helper.perform_create(payload, note_key)
                with open(self.done_medications_file, 'a') as done_medications:
                    done_medications.write(f"{medication['id']}|{medication['patient']}|{patient_key}|{canvas_id}\n")
                self.done_medications.add(medication['id'])
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_medications_file, 'a') as errored_medications:
                    errored_medications.write(f"{medication['id']}|{medication['patient']}|{patient_key}|{e}\n")

    def ingest_problems(self, patient_key, note_key, patients_problems):

        print(f'      Found {len(patients_problems)} problems')
        for problem in patients_problems:
            if problem['id'] in self.done_problems:
                continue

            if problem['snomed_ct_code'] == '55607006':
                continue

            coding = (
                ([{
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": problem['icd_code'],
                    "display": problem['name']
                }] if problem['icd_version'] == '10' and problem['icd_code'] else []) +
                ([{
                    "system": "http://snomed.info/sct",
                    "code": problem['snomed_ct_code'],
                    "display": problem['name']
                }] if problem['snomed_ct_code'] else [])
            )

            if not coding:
                continue

            payload = {
                "resourceType": "Condition",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_key,
                    }
                ],
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active" if problem['status'] == 'active' else "resolved",
                        }
                    ]
                },
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                "code": "encounter-diagnosis",
                                "display": "Encounter Diagnosis"
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": coding
                },
                "subject": {
                    "reference": f"Patient/{patient_key}"
                },
                "onsetDateTime": problem['date_diagnosis'],
                "note": [
                    {
                        "text": problem['notes']
                    }
                ] if problem['notes'] else []
            }
            # print(json.dumps(payload, indent=2))
            try:
                canvas_id = self.fumage_helper.perform_create(payload, note_key)
                with open(self.done_problems_file, 'a') as done_problems:
                    done_problems.write(f"{problem['id']}|{problem['patient']}|{patient_key}|{canvas_id}\n")
                    self.done_problems.add(problem['id'])
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_problems_file, 'a') as errored_problems:
                    errored_problems.write(f"{problem['id']}|{problem['patient']}|{patient_key}|{e}\n")

    def ingest_vaccines(self, patient_key, note_key, patients_vaccines):

        print(f'      Found {len(patients_vaccines)} vaccines')

        for vaccine in patients_vaccines:
            if vaccine['id'] in self.done_vaccines:
                print('  Vaccine already done...skipping')
                continue

            coding = self.vaccine_map.get(f"{vaccine['cvx_code']}|{vaccine['cpt_code']}|{vaccine['name']}")


            if not coding:
                with open(self.errored_vaccines_file, 'a') as errored_vaccines:
                    errored_vaccines.write(f"{vaccine['id']}|{vaccine['patient']}|{patient_key}|{vaccine['cvx_code']}|{vaccine['cpt_code']}|{vaccine['name']}|No vaccine coding found.\n")
                print('       No coding found')
                continue # ignore all rows that dont have a defined coding mapping yet


            vaccine_inventory = self.inventory_vaccines.get(vaccine['vaccine_inventory'])
            payload = {
                "resourceType": "Immunization",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_key
                    }
                ],
                "status": "completed",
                "vaccineCode": {
                    "coding": [{
                            "system": "http://hl7.org/fhir/sid/cvx",
                            "code": coding['cvx_code'],
                            "display": coding['medium_name']
                        }] if coding.get('cvx_code') else [{
                            "system": "http://www.ama-assn.org/go/cpt",
                            "code": coding['cpt_code'],
                            "display": coding['medium_name']
                        }]
                },
                "patient": {
                    "reference": f"Patient/{patient_key}",
                    "type": "Patient"
                },
                "occurrenceDateTime": vaccine['administration_start'][:10],
                "primarySource": False,
                "note": (
                    ([{"text": vaccine['comments']}] if vaccine['comments'] else []) +
                    ([{"text": f'Name: {vaccine_inventory[0]["name"]}, Lot number: {vaccine_inventory[0]["lot_number"]},  Expiration: {vaccine_inventory[0]["expiry"]}, Manufacturer: {vaccine_inventory[0]["manufacturer"]}'}] if vaccine_inventory else [])
                )
            }

            # print(json.dumps(payload, indent=2))
            try:
                canvas_id = self.fumage_helper.perform_create(payload, note_key)
                with open(self.done_vaccines_file, 'a') as done_vaccines:
                    done_vaccines.write(f"{vaccine['id']}|{vaccine['patient']}|{patient_key}|{canvas_id}\n")
                print('       Vaccine complete')
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_vaccines_file, 'a') as errored_vaccines:
                    errored_vaccines.write(f"{vaccine['id']}|{vaccine['patient']}|{patient_key}|{vaccine['cvx_code']}|{vaccine['cpt_code']}|{vaccine['name']}|{e}\n")
                print('       Vaccine error')

    def fetch_records_and_maps(self):
        self.allergies = self.drchrono_helper.fetch_drchrono_records_from_file('allergies', filename=self.allergies_file, param_string='verbose=True')
        self.allergen_map = self.create_allergy_coding_map('mappings/allergen_coding_map.json', self.allergies, "Allergen")
        self.medications = self.drchrono_helper.fetch_drchrono_records_from_file('medications', filename=self.medications_file)
        self.medication_map = self.create_medication_coding_map('mappings/medication_coding_map.json', self.medications, "Medication", lambda row: row['name'] == 'No Known Medications')
        self.problems = self.drchrono_helper.fetch_drchrono_records_from_file('problems', filename=self.problems_file)
        self.vaccines = self.drchrono_helper.fetch_drchrono_records_from_file('patient_vaccine_records', filename=self.vaccines_file)
        self.vaccine_map = self.create_vaccine_coding_map('mappings/vaccine_coding_map.json', self.vaccines)
        self.inventory_vaccines = self.drchrono_helper.fetch_drchrono_records_from_file('inventory_vaccines', filename='PHI/inventory_vaccines.csv', key='id')

        print('Done')

    def load(self):

        patient_count = len(self.patient_map)
        for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):
            if not self.vaccines.get(drchrono_patient_id, []):
                continue

            note_key = self.get_or_create_historical_data_input_note(canvas_patient_key, drchrono_patient_id)

            print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
            self.ingest_allergies(canvas_patient_key, note_key, self.allergies.get(drchrono_patient_id, []))
            self.ingest_medications(canvas_patient_key, note_key, self.medications.get(drchrono_patient_id, []))
            self.ingest_problems(canvas_patient_key, note_key, self.problems.get(drchrono_patient_id, []))
            self.ingest_vaccines(canvas_patient_key, note_key, self.vaccines.get(drchrono_patient_id, []))

            self.lock_note(note_key)

        print('Done')

    def ingest_patient_vaccines(self):

        patient_count = len(self.vaccines)
        for i, (drchrono_patient_id, vaccines) in enumerate(self.vaccines.items()):
            canvas_patient_key = self.patient_map[drchrono_patient_id]

            note_key = self.get_or_create_historical_data_input_note(canvas_patient_key, drchrono_patient_id)

            print(f'Creating Vaccine Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
            self.ingest_vaccines(canvas_patient_key, note_key, self.vaccines.get(drchrono_patient_id, []))

            self.lock_note(note_key)

        print('Done')

    def lock_all_notes(self):
        patient_count = len(self.patient_map)
        for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):

            if drchrono_patient_id in self.note_map:
                note_key = self.note_map[drchrono_patient_id][0]['note_key']
                print(f'Locking note for {drchrono_patient_id},{canvas_patient_key} ({i+1}/{patient_count})')
                self.lock_note(note_key)

                with open(self.finished_patient_file, 'a') as patients_finished:
                    patients_finished.write(f'{drchrono_patient_id}|{canvas_patient_key}\n')

    def deal_with_errored_medications(self):
        to_remap = set()
        with open(self.errored_medications_file, 'r') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                # id|patient|canvas_patient_key|error_message
                med_row = next(m for m in self.medications.get(row['patient']) if m['id'] == row['id'])
                found_code = self.medication_map.get(f"{med_row['rxnorm']}|{med_row['name']}")
                print(f"{med_row['id']},{med_row['rxnorm']},{med_row['name']},{found_code}")
                to_remap.add(f"{med_row['rxnorm']}|{med_row['name']} -> {found_code}")
        pprint(to_remap)


    def find_vaccines_to_ingest_as_unstructured(self, delimiter='|'):
        # loop through the errored_vaccines file and find the ones with the error message "No vaccine coding found"
        vaccine_to_ingest = []
        with open(self.errored_vaccines_file, 'r') as errored:
            reader = csv.DictReader(errored, delimiter=delimiter)
            for row in reader:
                if row['error_message'] == 'No vaccine coding found.':
                    drchrono_patient_id = row['patient']
                    canvas_patient_key = self.patient_map[drchrono_patient_id]

                    patient_vaccines = self.vaccines[drchrono_patient_id]
                    vaccine = next((v for v in self.vaccines[drchrono_patient_id] if v['id'] == row['id']), None)
                    vaccine_inventory = self.inventory_vaccines.get(vaccine['vaccine_inventory'])
                    vaccine_to_ingest.append({
                        "drchrono_vaccine_id": vaccine['id'],
                        "drchrono_patient_id": drchrono_patient_id,
                        "note_key": self.get_or_create_historical_data_input_note(canvas_patient_key, drchrono_patient_id),
                        "vaccine_name": vaccine['name'],
                        "patient": canvas_patient_key,
                        "date": vaccine['administration_start'][:10],
                        "note": "\n".join(
                            ([vaccine['comments']] if vaccine['comments'] else []) +
                            ([f'Name: {vaccine_inventory[0]["name"]}, Lot number: {vaccine_inventory[0]["lot_number"]},  Expiration: {vaccine_inventory[0]["expiry"]}, Manufacturer: {vaccine_inventory[0]["manufacturer"]}'] if vaccine_inventory else [])
                        )
                    })
        with open("PHI/unstructured_vaccine_records.json", 'w', encoding='utf-8') as f:
            json.dump(vaccine_to_ingest, f, ensure_ascii=False, indent=4)



if __name__ == '__main__':
    loader = DataImportLoader(environment='juno')
    loader.fetch_records_and_maps()
    loader.load()
    #loader.lock_all_notes()
    # loader.ingest_patient_vaccines()
    # loader.find_vaccines_to_ingest_as_unstructured()
