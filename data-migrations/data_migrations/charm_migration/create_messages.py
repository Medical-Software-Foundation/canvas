from data_migrations.utils import (
    fetch_from_json,
    write_to_json
)

from data_migrations.charm_migration.utils import CharmPatientAPI


class MessageLoader:
    def __init__(self, environment) -> None:
        self.json_file = "PHI/messages.json"
        self.csv_file = "PHI/messages.csv"
        self.environment = environment
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)

    def make_json(self):
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        messages = charm_patient_api.fetch_messages(patient_ids=patient_ids)
        write_to_json(self.json_file, messages)


if __name__ == "__main__":
    loader = MessageLoader(environment='phi-ways2well-test')
    loader.make_json()
