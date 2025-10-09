from data_migrations.utils import (
    fetch_from_json,
    write_to_json
)

from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.message import MessageLoaderMixin


class MessageLoader(MessageLoaderMixin):
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
        charm_patient_api.fetch_messages(patient_ids=patient_ids, file_path=self.json_file)

    def make_csv(self):
        headers = [
            "ID",
            "Timestamp",
            "Recipient",
            "Sender",
            "Text",
            "Thread ID"
        ]

        data = fetch_from_json(self.json_file)
        with open(self.csv_file, "w") as fhandle:
            pass




if __name__ == "__main__":
    loader = MessageLoader(environment='ways2well')
    loader.make_json()
