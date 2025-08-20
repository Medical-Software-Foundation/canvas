from data_migrations.utils import (
    fetch_from_json,
    load_fhir_settings,
    write_to_json
)
from data_migrations.template_migration.immunization import ImmunizationMixin
from data_migrations.charm_migration.utils import CharmPatientAPI


class ImmunizationLoader(ImmunizationMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.json_file = "PHI/immunizations.json"
        self.csv_file = "PHI/immunizations.csv"
        self.fumage_helper = load_fhir_settings(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)

    def make_json(self):
        patient_ids = list(self.patient_map.keys())
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        immunizations = charm_patient_api.fetch_vaccines(patient_ids=patient_ids)
        write_to_json(self.json_file, immunizations)


if __name__ == "__main__":
    loader = ImmunizationLoader(environment="phi-ways2well-test")
    loader.make_json()
