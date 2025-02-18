import csv

from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import fetch_from_json, write_to_json, load_fhir_settings


class PrescriptionLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.json_file = "PHI/prescriptions.json"
        self.csv_file = "PHI/prescriptions.csv"
        self.med_mapping_file = 'mappings/medication_coding_map.json'
        self.fumage_helper = load_fhir_settings(environment=environment)

    def make_fdb_mapping(self, delimiter='|'):
        fdb_mapping_dict = {}
        with open(self.csv_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                key = f"{row['Medication Name']}|"
                if key not in fdb_mapping_dict:
                    print(key)
                    fdb_mapping_dict[key] = []

        write_to_json(self.med_mapping_file, fdb_mapping_dict)

    def make_csv(self, delimiter="|"):
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

        headers = [
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in prescriptions:
                writer.writerow({
                    "ID": row["id"],
                    "Patient Identifier": row["patient"],
                    "Status": "active" if not row["inactive_at"] else "inactive",
                    "RxNorm/FDB Code": "unstructured",
                    "SIG": row["directions"],
                    "Medication Name": row["name"],
                })

        print("Successfully made CSV")


if __name__ == "__main__":
    loader = PrescriptionLoader(environment='phi-collaborative-test')
    delimiter = '|'

    # loader.make_csv(delimiter=delimiter)
    loader.make_fdb_mapping()
    loader.map()
