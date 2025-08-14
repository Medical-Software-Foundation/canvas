import csv

from data_migrations.template_migration.allergy import AllergyLoaderMixin
from data_migrations.utils import (
    fetch_from_json,
    load_fhir_settings,
    write_to_json,
    fetch_complete_csv_rows
)
from data_migrations.charm_migration.utils import CharmFHIRAPI, CharmPatientAPI
from data_migrations.template_migration.utils import FileWriterMixin


class AllergyLoader(AllergyLoaderMixin, FileWriterMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.csv_file = "PHI/allergies.csv"
        self.json_file = "PHI/allergies.json"
        self.patient_api_json_file = "PHI/allergies_patient_api.json"
        self.fhir_api_json_file = "PHI/allergies_fhir_api.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.done_file = 'results/done_allergies.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_allergies.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_allergies.csv'
        self.fumage_helper = load_fhir_settings(environment)
        self.validation_error_file = "results/PHI/errored_allergy_validation.json"

        self.allergy_map_file = "mappings/allergy_coding_map.json"

        self.default_location = None # TODO - populate this
        self.default_note_type_name = "Charm Historical Note"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        super().__init__()

    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_ids = list(self.patient_map.keys())
        allergy_list = charm_patient_api.fetch_allergies(patient_ids=patient_ids)
        write_to_json(self.patient_api_json_file, allergy_list)

    def make_fhir_api_json(self):
        charm_fhir_api = CharmFHIRAPI(environment=self.environment)
        fhir_allergies = charm_fhir_api.fetch_allergies()
        write_to_json(self.fhir_api_json_file, fhir_allergies)

    def make_json(self):
        # combines the Patient API data with codings from the FHIR API
        output = []
        patient_api_data = fetch_from_json(self.patient_api_json_file)
        fhir_api_data = fetch_from_json(self.fhir_api_json_file)

        allergy_id_coding_map = {}
        for f_allergy in fhir_api_data:
            if codings := f_allergy["resource"].get("code", {}).get("coding"):
                allergy_id_coding_map[f_allergy["resource"]["id"]] = codings

        for p_allergy in patient_api_data:
            p_allergy["codings"] = allergy_id_coding_map.get(p_allergy["patient_allergy_id"], [])
            output.append(p_allergy)
        write_to_json(self.json_file, output)

    def make_allergy_map_file(self):
        allergy_map = {}
        allergy_data = fetch_from_json(self.json_file)
        for allergy in allergy_data:
            rx_norm_code = ""
            rx_norm_codes = [c["code"] for c in allergy["codings"] if "rxnorm" in c["system"]]
            if rx_norm_codes:
                rx_norm_code = rx_norm_codes[0]

            if allergy["allergen"] not in allergy_map:
                allergy_map[f"{allergy['allergen']}|{rx_norm_code}"] = []
        write_to_json(self.allergy_map_file, allergy_map)


if __name__ == "__main__":
    allergy_loader = AllergyLoader("phi-ways2well-test")
    # allergy_loader.make_patient_api_json()
    # allergy_loader.make_fhir_api_json()
    # allergy_loader.make_json()
    allergy_loader.make_allergy_map_file()
