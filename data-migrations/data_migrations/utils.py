import csv, json, requests
from urllib.parse import urlencode
from decouple import Config, RepositoryIni
from collections import defaultdict

def fetch_complete_csv_rows(filename, key='id', delimiter='|'):
    """
        Return a distinct set of all the unique identifiers of a csv.
        Used to know what records have already been processed to avoid
        duplicating records
    """
    with open(filename, 'r') as file:
        reader = csv.DictReader(file, delimiter=delimiter)
        return {row[key] for row in reader}

def fetch_from_json(filename):
    """
        Load a JSON File
    """
    with open(filename) as json_data:
        return json.load(json_data)

def write_to_json(filename, data):
    """
        Write a dict to a JSON file
    """
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Successfully created {filename}")

def fetch_from_csv(filename, key='patient', delimiter=','):
    """
        Load a CSV file and
        return as a dict with the argument key as the keys and a list of all the
        records for that unique key
    """
    data = defaultdict(list)
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            # ignore patients we didn't ingest in the instance
            if key == 'patient' and row[key] not in self.patient_map:
                continue

            data[row[key]].append(row)

    return data

def read_json_file(path_to_file, is_fhir=False, list_attribute=None):
    """ Each of the JSON files given has each line corresponding to
    all the records related to one patient.

    We want to return a dictionary with the patient's athenapatientid as the key,
    so we can iterate over each patient when ingesting data
    """
    records = {}
    with open(path_to_file, 'r') as file:
        for line in file:
            line = line.replace('true', 'True').replace('false', 'False')
            line = eval(line)

            if is_fhir:
                _list = line.get(list_attribute, [])
                new_list = []
                key = None
                for item in _list:
                    if 'subject' not in item and 'patient' not in item:
                        continue
                    key = (item.get('subject') or item.get('patient'))['reference']
                    new_list.append(item)

                if not key:
                    raise Exception(f"No Patient key was found for row {_list}")
                records[key] = new_list
            else:
                patient_details = line.get('patientdetails', {})
                key = patient_details.get('enterpriseid')

                if not key:
                    raise Exception(f"No Patient key was found for row {line}")

                records[key] = line

    return records

def get_ontologies_token(environment):
    ini = RepositoryIni('../config.ini')
    ini.SECTION = environment
    config = Config(ini)

    return config("ontologies_key", cast=str)


def reverse_mapping(json_file):
    # Reverses a mapping file by swapping the key/value positions.
    data_dict = fetch_from_json(json_file)
    return {val: key for key, val in data_dict.items()}


def load_fhir_settings(environment):
    """
        Used to authenticate
    """
    ini = RepositoryIni('../config.ini')
    ini.SECTION = environment
    config = Config(ini)

    client_id = config("client_id", cast=str)
    client_secret = config("client_secret", cast=str)

    fumage = FHIRHelper({'INSTANCE_NAME': environment, 'CLIENT_ID': client_id, 'CLIENT_SECRET': client_secret})
    return fumage

class FHIRHelper:
    """
    Helper class to take care of all the FHIR auth and calls
    """
    def __init__(self, settings):
        self.client_id = settings.get("CLIENT_ID")
        self.client_secret = settings.get("CLIENT_SECRET")
        self.instance_name = settings.get("INSTANCE_NAME")

        if self.instance_name == "localhost":
            self.base_url = "http://localhost:8000"
            self.base_fhir_url = "http://localhost:8888"
        else:
            self.base_url = f"https://{self.instance_name}.canvasmedical.com"
            self.base_fhir_url = f"https://fumage-{self.instance_name}.canvasmedical.com"

        self.get_fhir_api_token()
        if not self.client_id or not self.client_secret or not self.instance_name:
            raise Exception(
                f"Unable to perform FHIR API requests without CLIENT_ID, CLIENT_SECRET, and INSTANCE_NAME. \n"
            )
    def get_fhir_api_token(self) -> str | None:
        """
        Requests and returns a bearer token for authentication to FHIR.
        """
        grant_type = "client_credentials"

        token_response = requests.post(
            f"{self.base_url}/auth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=f"grant_type={grant_type}&client_id={self.client_id}&client_secret={self.client_secret}",
        )

        if token_response.status_code != requests.codes.ok:
            raise Exception(
                "Unable to get a valid FHIR bearer token. \n"
                f"Verify that your CLIENT_ID and CLIENT_SECRET Protocol Settings (found here: {self.base_url}/admin/api/protocolsetting/) \n"
                f"match what is defined for your FHIR API third-party application (found here: {self.base_url}/auth/applications/)"
            )

        token = token_response.json().get("access_token")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        return token

    def read(self, resource_type: str, resource_id: str) -> requests.Response:
        """
        Given a resource_type (str) and resource_id (str), returns the requested FHIR resource.
        """
        return requests.get(
            f"{self.base_fhir_url}/{resource_type}/{resource_id}", headers=self.headers
        )

    def search(
        self, resource_type: str, search_params: dict | None = None
    ) -> requests.Response:
        """
        Given a resource_type (str) and search_params (dict), searches and returns a bundle of FHIR resources.
        """
        params = urlencode(search_params, doseq=True) if search_params else ""
        return requests.get(
            f"{self.base_fhir_url}/{resource_type}?{params}", headers=self.headers
        )

    def create(self, resource_type: str, payload: dict) -> requests.Response:
        """
        Given a resource_type (str) and FHIR resource payload (dict), creates and returns a FHIR resource.
        """
        return requests.post(
            f"{self.base_fhir_url}/{resource_type}",
            json=payload,
            headers=self.headers,
        )

    def perform_create(self, payload):
        """
        Make a FHIR Create call and return the ID of the resource created
        or raise an error if it failed to create
        """

        response = self.create(payload['resourceType'], payload)

        if response.status_code == 401:
            self.get_fhir_api_token()
            return self.perform_create(payload)

        if response.status_code != 201:
            raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

        return response.headers['location'].replace(f'http://fumage-{self.instance_name}.canvasmedical.com/{payload["resourceType"]}/', '').replace('/_history/1', '').replace(f'http://localhost:8888/{payload["resourceType"]}/', '')

    def update(
        self, resource_type: str, resource_id: str, payload: dict
    ) -> requests.Response:
        """
        Given a resource_type (str), resource_id (str), and FHIR resource payload (dict), updates and returns a FHIR resource.
        """
        return requests.put(
            f"{self.base_fhir_url}/{resource_type}/{resource_id}",
            json=payload,
            headers=self.headers,
        )

    def build_patient_external_identifier_map(self, system, output_file):
        """ When ingesting patients from an EMR into Canvas, it is best that the
        unique identifier for that patient in the EMR is loaded as an identifier in the
        FHIR Patient Create endpoint. So this function will create a JSON
        map of the EMR identifier to the canvas patient key.

        This will help ensure all the historic records are added to the correct patient chart
        """

        search_parameters = {
            '_sort': 'pk',
            '_count': 100,
            '_offset': 0,
            'identifier': f'{system}|'
        }

        patients = {}
        while True:
            response = self.search("Patient", search_parameters)

            if response.status_code != 200:
                raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

            print(f'Performed search with url: {response.url}')
            response_json = response.json()
            for item in response_json['entry']:
                for identifier in item['resource']['identifier']:
                    if identifier['system'] == system:
                        patients[identifier['value']] = item['resource']['id']

            next = any([l['relation'] == 'next' for l in response_json['link']])
            if not next:
                break
            search_parameters['_offset'] = search_parameters['_offset'] + search_parameters['_count']

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(patients, f, ensure_ascii=False, indent=4)

    def does_appointment_already_exists(self, start_time, canvas_patient_key):
        """
            Checks if an appointment for a patient at a specific time already exits
        """

        search_parameters = {
            "patient": f"Patient/{canvas_patient_key}",
            "date": f"eq{arrow.get(start_time)}"
        }
        response = self.search('Appointment', search_parameters)

        if response.status_code != 200:
            raise Exception(f"Failed to find appointments with {response.url} and error {response.text}")

        total = response.json()['total']
        if total:
            return True

        return False

    def check_in_and_lock_appointment(self, canvas_appointment_id, note_id=None):
        """
            For a historical data migration, we want to mark all appointments loaded and completed,
            so this function will find the note associated to each appointment,
            check in the note and then lock the note via the Note API
        """
        if canvas_appointment_id and not note_id:
            read_response = self.read("Appointment", canvas_appointment_id)
            if read_response.status_code != 200:
                raise Exception("Failed to find appointment note to lock")

            note_id = read_response.json()["extension"][0]['valueId']

        base_url = f"{self.base_url}/core/api/notes/v1/Note/{note_id}"

        check_in_response = requests.request("PATCH", base_url, headers=self.headers, data=json.dumps({"stateChange": "CVD"}))
        if check_in_response.status_code != 200 and 'CVD -> CVD' not in check_in_response.text:
            raise Exception(f"Failed to perform {check_in_response.url}. \n {check_in_response.text}")

        lock_response = requests.request("PATCH", base_url, headers=self.headers, data=json.dumps({"stateChange": "LKD"}))
        if lock_response.status_code != 200:
            raise Exception(f"Failed to perform {lock_response.url}. \n {lock_response.text}")

