from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
    write_to_json
)


class ConditionLoader(ConditionLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.patient_api_json_file = "PHI/conditions_patient_api.json"
        self.csv_file = "PHI/conditions.csv"
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.done_file = "results/done_conditions.csv"
        self.error_file = "results/errored_conditions.csv"
        self.ignore_file = "results/ignored_conditions.csv"
        self.validation_error_file = 'results/PHI/errored_condition_validation.json'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        self.default_location = None # TODO - populate this
        self.default_note_type_name = "Charm Historical Note"


    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)

        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]

        condition_list = charm_patient_api.fetch_diagnoses(patient_ids=patient_ids)
        write_to_json(self.patient_api_json_file, condition_list)


if __name__ == "__main__":
    loader = ConditionLoader(environment="phi-ways2well-test")
    loader.make_patient_api_json()
