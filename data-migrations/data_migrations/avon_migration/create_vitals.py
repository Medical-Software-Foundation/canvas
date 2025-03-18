import csv
import os

from data_migrations.template_migration.vitals import VitalsMixin
from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
)


class VitalsLoader(VitalsMixin):
    def __init__(self, environment) -> None:
        self.json_file = "PHI/vitals.json"
        self.csv_file = "PHI/vitals.csv"
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.fumage_helper = load_fhir_settings(environment)
        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.error_file = 'results/errored_vitals.csv'
        self.done_file = 'results/done_vitals.csv'
        self.ignore_file = 'results/ignored_vitals.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.validation_error_file = "results/PHI/errored_vitals_validation.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)

        super().__init__()


    def make_csv(self):
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/vitals", self.json_file, param_string='')

        headers = [
            "id",
            "patient",
            "height",
            "weight_lbs",
            "body_temperature",
            "blood_pressure_systole",
            "blood_pressure_diastole",
            "pulse",
            "respiration_rate",
            "oxygen_saturation",
            "created_by",
            "created_at",
            "comment",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in data:
                row_to_write = {
                    "id": row["id"],
                    "patient": row["patient"],
                    "height": row["height"],
                    "weight_lbs": str(row["weight"]) if row["weight"] else "",
                    "body_temperature": row["temperature"] or "",
                    "blood_pressure_systole": row.get("blood_pressure", {}).get("systolic", "") if row["blood_pressure"] else "",
                    "blood_pressure_diastole": row.get("blood_pressure", {}).get("diastolic", "") if row["blood_pressure"] else "",
                    "pulse": row["pulse"],
                    "respiration_rate": row["respiratory_rate"],
                    "oxygen_saturation": row["oxygen_saturation"],
                    "created_by": row["created_by"],
                    "created_at": row["created_at"],
                    "comment": row["comment"] or "",
                }

                writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = VitalsLoader('phi-collaborative-test')
    #loader.make_csv()

    valid_rows = loader.validate()
    loader.load(valid_rows)
