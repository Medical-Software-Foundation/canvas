import csv
import os

from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import fetch_complete_csv_rows, fetch_from_json, write_to_json, load_fhir_settings


class PrescriptionLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.json_file = "PHI/prescriptions.json"
        self.csv_file = "PHI/prescriptions.csv"
        self.med_mapping_file = 'mappings/medication_coding_map.json'
        self.med_mapping = fetch_from_json(self.med_mapping_file)
        self.fumage_helper = load_fhir_settings(environment=environment)
        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        self.validation_error_file = "results/PHI/errored_prescription_validation.json"
        self.ignore_file = "results/ignored_prescriptions.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_prescriptions.csv'
        self.done_file = 'results/done_prescriptions.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        super().__init__(*args, **kwargs)

    def make_fdb_mapping(self, delimiter='|'):
        fdb_mapping_dict = fetch_from_json(self.med_mapping_file)
        reader = fetch_from_json(self.json_file)
        for row in reader:
            key = f"{row['name']}|"
            if key not in fdb_mapping_dict:
                print(key)
                fdb_mapping_dict[key] = []

        write_to_json(self.med_mapping_file, fdb_mapping_dict)

    def make_json(self):
        prescriptions = []

        for patient_id in fetch_from_json(self.patient_map_file).keys():
            try:
                print(f"Fetching prescriptions for patient id {patient_id}")
                data = self.avon_helper.fetch_records("v2/prescriptions", None, f"patient={patient_id}")
            except Exception as e:
                print(f"Exception fetching prescriptions for {patient_id}: {e}")
                continue
            prescriptions.extend(data)

        write_to_json(self.json_file, prescriptions)

    def make_csv(self, delimiter="|"):
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        prescriptions = fetch_from_json(self.json_file)

        headers = [
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
            "Original Code",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in prescriptions:

                mapping_found = self.med_mapping.get(f"{row['name']}|")
                if mapping_found:
                    code = next(item['code'] for item in mapping_found if item["system"] == 'http://www.fdbhealth.com/')
                    if not code:
                        code = "unstructured"
                else:
                    print(f"Unstructured for {row['name']}")
                    code = "unstructured"

                patient_identifier = row['patient']
                if patient_identifier.startswith("user_user_"):
                    patient_identifier = patient_identifier.replace("user_user_", "user_")

                writer.writerow({
                    "ID": row["id"],
                    "Patient Identifier": patient_identifier,
                    "Status": "active" if not row["inactive_at"] else "inactive",
                    "RxNorm/FDB Code": code,
                    "SIG": row["directions"],
                    "Medication Name": row["name"],
                    "Original Code": ""
                })

        print("Successfully made CSV")


if __name__ == "__main__":
    loader = PrescriptionLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_json()

    #loader.make_fdb_mapping()
    # loader.map()

    #loader.make_csv(delimiter=delimiter)

    valid_rows = loader.validate(delimiter=delimiter)
    #loader.load(valid_rows)
    loader.load_via_commands_api(valid_rows)
