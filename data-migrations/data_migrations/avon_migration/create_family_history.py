import csv
import os

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.template_migration.family_history import FamilyHistoryMixin
from data_migrations.utils import fetch_from_json, load_fhir_settings, fetch_complete_csv_rows


class FamilyHistoryLoader(FamilyHistoryMixin):
    def __init__(self, environment, *args, **kwargs) -> None:
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.json_file = "PHI/family_history.json"
        self.csv_file = "PHI/family_history.csv"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.relationship_coding_map_file = "mappings/relationship_coding_map.json"
        self.relationship_coding_map = fetch_from_json(self.relationship_coding_map_file)
        self.validation_error_file = 'results/PHI/errored_family_history_validation.json'
        self.fumage_helper = load_fhir_settings(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.done_file = 'results/done_family_history.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.icd10_to_snomed_mapping = fetch_from_json("mappings/icd10_to_snomed_map.json")
        self.icd10_map_file = "../template_migration/mappings/icd10_map.json"
        self.icd10_map = fetch_from_json(self.icd10_map_file)
        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"

        self.ignore_file = 'results/ignored_family_history.csv'
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)

        self.error_file = 'results/errored_family_history.csv'

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter):
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/family_histories", self.json_file, param_string='')

        headers = [
            "id",
            "patient",
            "relative_coding",
            "comment",
            "icd_code",
            "diagnosis_description",
            "provider"
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                row_to_write = {
                    "id": row["id"],
                    "patient": row["patient"],
                    "relative_coding": row["relationship"],
                    "comment": row["comment"].replace("\n", "\\n") if row["comment"] else "",
                    "provider": row["created_by"]
                }
                for diagnosis in row["diagnoses"]:
                    row_to_write["icd_code"] = diagnosis["diagnosis"]
                    row_to_write["diagnosis_description"] = diagnosis.get("description", "")
                    writer.writerow(row_to_write)

        print("CSV successfully created")


if __name__ == "__main__":
    loader = FamilyHistoryLoader('phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter="|")
    loader.load(valid_rows)
