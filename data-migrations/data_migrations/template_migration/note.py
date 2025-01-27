import arrow
import json
import requests

from data_migrations.utils import write_to_json


class NoteMixin:
    def __init__(self) -> None:
        uri = "/core/api/notes/v1/Note"
        if self.environment == "localhost":
            self.base_url = f"http://localhost:8000{uri}"
        else:
            self.base_url = f"https://{self.environment}.canvasmedical.com{uri}"

    def get_or_create_historical_data_input_note(self, canvas_patient_key, **kwargs) -> str:
        """
        Valid kwargs:

        note_type_name (historical note type name)
        encounter_start_time (as isoformat string)
        practice_location_key
        """
        if canvas_patient_key in self.note_map:
            return self.note_map[canvas_patient_key]

        payload = {
            "noteTypeName": kwargs.get("note_type_name", self.default_note_type_name),
            "patientKey": canvas_patient_key,
            "providerKey": "5eede137ecfe4124b8b773040e33be14", # canvas bot
            "encounterStartTime": kwargs.get("encounter_start_time", arrow.now().isoformat()),
            "practiceLocationKey": kwargs.get("practice_location_key", self.default_location)
        }

        response = requests.request("POST", self.base_url, headers=self.fumage_helper.headers, data=json.dumps(payload))

        if response.status_code != 201:
            raise Exception(f"Failed to perform {response.url}. \n {response.text}")

        response_json = response.json()
        note_key = response_json['noteKey']

        self.note_map[canvas_patient_key] = note_key
        write_to_json(self.note_map_file, self.note_map)

        return note_key
