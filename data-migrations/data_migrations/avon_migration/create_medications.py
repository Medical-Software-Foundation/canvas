import csv, os

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.utils import fetch_from_json, write_to_json, load_fhir_settings, fetch_complete_csv_rows


class MedicationLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.environment = environment
        self.json_file = "PHI/medications.json"
        self.csv_file = 'PHI/medications.csv'
        self.avon_helper = AvonHelper(environment)
        self.med_mapping_file = 'mappings/medication_coding_map.json'
        self.fumage_helper = load_fhir_settings(environment)
        self.validation_error_file = 'results/PHI/errored_medication_validation.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.done_file = 'results/done_medications.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = 'results/errored_medications.csv'
        self.ignore_file = 'results/ignored_medications.csv'

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        super().__init__(*args, **kwargs)

    def make_fdb_mapping(self, delimiter='|'):
        data = fetch_from_json(self.json_file)
        fdb_mapping_dict = {}
        for row in data:
            if row['name']:
                key = f"{row['name']}|"
                if key not in fdb_mapping_dict:
                    fdb_mapping_dict[key] = []
        write_to_json(self.med_mapping_file, fdb_mapping_dict)

    def make_csv(self, delimiter="|") -> None:
        """
            Fetch the Medication Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/medications", self.json_file, param_string='')
        # data = fetch_from_json(self.json_file)

        headers = {
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
            "Original Code",
        }

        with open(self.csv_file, 'w') as fhandle:
            writer = csv.DictWriter(fhandle, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                if not row['name'] or row['name'] == '—':
                    self.ignore_row(row['id'], "No medication name found")
                    continue

                medication_status = None
                if row["active"] is True:
                    medication_status = "active"
                elif row["active"] is False:
                    medication_status = "active"

                writer.writerow(
                    {
                        "ID": row["id"],
                        "Patient Identifier": row["patient"],
                        "Status": medication_status or "active",
                        "RxNorm/FDB Code": "unstructured",
                        "SIG": row["sig"] or "",
                        "Medication Name": row["name"] or "",
                        "Original Code": ""
                    }
                )
            print("CSV successfully made")


if __name__ == "__main__":
    loader = MedicationLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter=delimiter)
    loader.load(valid_rows)
