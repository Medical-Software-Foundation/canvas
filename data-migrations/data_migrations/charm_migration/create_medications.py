from data_migrations.charm_migration.utils import CharmFHIRAPI, CharmPatientAPI
from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.utils import (
    fetch_from_json, write_to_json,
    load_fhir_settings,
    fetch_complete_csv_rows
)


class MedicationLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/medications.json"
        self.patient_api_json_file = "PHI/medications_patient_api.json"
        self.fhir_api_json_file = "PHI/medications_fhir_api.json"
        self.fhir_api_medication_entries_json_file = "PHI/medication_entries_fhir_api.json"
        self.patient_api_supplement_json_file = "PHI/supplements_patient_api.json"
        self.csv_file = 'PHI/medications.csv'
        self.fumage_helper = load_fhir_settings(environment)
        self.med_mapping_file = "mappings/medication_coding_map.json"
        self.med_mapping = fetch_from_json(self.med_mapping_file)
        self.ignore_file = "results/ignored_medications.csv"
        self.done_file = "results/done_medications.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = "results/errored_medications.csv"
        self.validation_error_file = "results/PHI/errored_medication_validation.json"
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        self.default_location = None # TODO - populate this
        self.default_note_type_name = "Charm Historical Note"

    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_ids = list(self.patient_map.keys())
        medication_list = charm_patient_api.fetch_medications(patient_ids=patient_ids)
        write_to_json(self.patient_api_json_file, medication_list)

    def make_patient_api_supplements_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]
        supplement_list = charm_patient_api.fetch_supplements(patient_ids=patient_ids)
        write_to_json(self.patient_api_supplement_json_file, supplement_list)

    def make_fhir_api_json(self):
        charm_fhir_api = CharmFHIRAPI(environment=self.environment)
        medication_administration_list = charm_fhir_api.fetch_medication_requests()
        write_to_json(self.fhir_api_json_file, medication_administration_list)

    def make_medication_entry_json(self):
        charm_fhir_api = CharmFHIRAPI(environment=self.environment)
        patient_api_medications = fetch_from_json(self.patient_api_json_file)
        medication_id_list = list(set([m["drug_details_id"] for m in patient_api_medications if m["drug_details_id"]]))
        medication_entries = charm_fhir_api.fetch_medication_entries(medication_id_list)
        write_to_json(self.fhir_api_medication_entries_json_file, medication_entries)

    def combine_medication_data(self):
        # combines the medication data from the different sources (patient API, FHIR API) to a single file
        output_data = []
        patient_api_data = fetch_from_json(self.patient_api_json_file)
        medication_entry_data = fetch_from_json(self.fhir_api_medication_entries_json_file)

        drug_details_map = {}
        for entry in medication_entry_data:
            drug_details_map[entry["id"]] = {"rxnorm_code": "", "display": ""}
            rxnorm_coding_list = [c for c in entry["code"]["coding"] if c["system"] == "http://www.nlm.nih.gov/research/umls/rxnorm"]
            if rxnorm_coding_list:
                rxnorm_code = rxnorm_coding_list[0].get("code", "")
                display = rxnorm_coding_list[0].get("display", "")
                if not display:
                    display = entry["code"].get("text", "")
                drug_details_map[entry["id"]]["rxnorm_code"] = rxnorm_code
                drug_details_map[entry["id"]]["display"] = display

        for medication in patient_api_data:
            drug_id = medication["drug_details_id"]
            medication["rxnorm"] = drug_details_map[drug_id]
            output_data.append(medication)
        write_to_json(self.json_file, output_data)


if __name__ == "__main__":
    loader = MedicationLoader(environment="phi-ways2well-test")
    # loader.make_patient_api_json()
    # loader.make_fhir_api_json()

    # loader.make_medication_entry_json()
    # loader.combine_medication_data()

    loader.make_patient_api_supplements_json()
