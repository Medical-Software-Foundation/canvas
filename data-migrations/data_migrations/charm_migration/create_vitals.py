from data_migrations.template_migration.vitals import VitalsMixin
from data_migrations.utils import (
    fetch_from_json,
    write_to_json
)

from data_migrations.charm_migration.utils import CharmPatientAPI


class VitalsLoader(VitalsMixin):
    def __init__(self, environment) -> None:
        self.json_file = "PHI/vitals.json"
        self.csv_file = "PHI/vitals.csv"
        self.environment = environment
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        super().__init__()

    def make_json(self):
        patient_ids = list(self.patient_map.keys())
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        vitals = charm_patient_api.fetch_vitals(patient_ids=patient_ids)
        write_to_json(self.json_file, vitals)


if __name__ == "__main__":
    loader = VitalsLoader(environment='phi-ways2well-test')
    loader.make_json()
