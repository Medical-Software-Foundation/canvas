import csv
import os

from data_migrations.template_migration.allergy import AllergyLoaderMixin
from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings


class AllergyLoader(AllergyLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.json_file = "PHI/allergies.json"
        self.csv_file = "PHI/allergies.csv"
        self.mapping_file = "mappings/allergy_map.json"
        self.allergy_map = fetch_from_json(self.mapping_file)
        self.ignore_file = "results/ignored_allergies.csv"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.done_file = 'results/done_allergies.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = 'results/errored_allergies.csv'
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.validation_error_file = 'results/PHI/errored_allergy_validation.json'

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|') -> None:
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/allergies", self.json_file, param_string='')

        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                # Ignore any allergies without a name
                if not row["name"] or row["name"] == "—":
                    self.ignore_row(row["id"], "Allergy is missing a name")
                    continue

                clinical_status = None
                if row["active"] is True or row["active"] is None:
                    clinical_status = "active"
                elif row["active"] is False:
                    clinical_status = "inactive"

                # most records have the patient id in created_by;
                # since we need the provider, we will blank out recorded_provider
                # if that is the case;
                recorded_provider = row["created_by"]
                if row["patient"] == recorded_provider or not recorded_provider or recorded_provider == "user_null":
                    recorded_provider = ""

                row_to_write = {
                    "ID": row["id"],
                    "Patient Identifier": row["patient"],
                    "Clinical Status": clinical_status,
                    "Type": "allergy",
                    "Onset Date": row["onset_date"] or "",
                    "Reaction": row["reaction"] or "",
                    "Recorded Provider": recorded_provider,
                }

                fdb_codes = self.allergy_map.get(row["name"].strip(), [])
                if fdb_codes:
                    row_to_write["FDB Code"] = "```".join(fdb_codes)
                    row_to_write["Free Text Note"] = row["comment"] or ""
                    row_to_write["Name"] = row["name"]
                else:
                    print(f"No mapping for {row['name']}")

                    row_to_write["FDB Code"] = "1-143" # Code for no allergy information available
                    free_text_note = row["name"]
                    if row["comment"]:
                        free_text_note = fr"{free_text_note}\\n{row['comment']}"
                    row_to_write["Free Text Note"] = free_text_note
                    row_to_write["Name"] = "No Allergy Information Available"

                writer.writerow(row_to_write)


if __name__ == "__main__":
    # change the customer_identifier to what is defined in your config.ini file
    loader = AllergyLoader(environment='phi-collaborative-test')
    delimiter = '|'

    # Make the Avon API call to their List Appointments endpoint and convert the JSON return
    # to the template CSV loader
    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows)
