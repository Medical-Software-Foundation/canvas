import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings

from data_migrations.template_migration.surgical_history import SurgicalHistoryMixin


class ConditionsAsSurgicalHistoryLoader(SurgicalHistoryMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.done_file = "results/done_conditions_as_surgical_history.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = "results/errored_conditions_as_surgical_history.csv"
        self.ignore_file = "results/ignored_conditions_as_surgical_history.csv"
        self.json_file = "PHI/conditions.json"
        self.csv_file = "PHI/conditions_as_surgical_history.csv"
        self.snomed_mapping_file = "mappings/condition_surgical_history_snomed_mapping.json"
        self.snomed_mapping = fetch_from_json(self.snomed_mapping_file)
        self.validation_error_file = "results/PHI/errored_condition_as_surgical_history_validation.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.default_note_type_name = "Charm Historical Note"
        self.fumage_helper = load_fhir_settings(environment)

    def make_csv(self):
        data = fetch_from_json(self.json_file)
        headers = [
            "id",
            "patient",
            "comment",
            "date_performed",
            "snomed_code",
            "snomed_text",
        ]

        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(fhandle, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in data:
                patient_id = row["patient_id"]
                for diagnosis in row["diagnoses"]:

                    condition_text = diagnosis["diagnosis_name"]
                    condition_code_type = diagnosis["code_type"]
                    if condition_code_type == "ICD10":
                        condition_icd10_code = diagnosis["code"]
                    else:
                        condition_icd10_code = ""

                    mapping_key = f"{condition_text}|{condition_icd10_code}"
                    if mapping_key in self.snomed_mapping:
                        snomed_dict = self.snomed_mapping[mapping_key]
                        row_to_write = {
                            "id": diagnosis["patient_diagnosis_id"],
                            "patient": patient_id,
                            "comment": diagnosis["comments"],
                            "date_performed": diagnosis["from_date"],
                            "snomed_code": snomed_dict["code"],
                            "snomed_text": snomed_dict["display"],
                        }
                        writer.writerow(row_to_write)
        print(f"Successfully wrote to {self.csv_file}")


if __name__ == "__main__":
    loader = ConditionsAsSurgicalHistoryLoader("ways2well")
    # loader.make_csv()
    valid_rows = loader.validate(delimiter=",")
    loader.load(valid_rows)
