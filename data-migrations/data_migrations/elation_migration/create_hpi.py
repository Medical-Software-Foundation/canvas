import os, arrow, csv
from collections import defaultdict

from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings, write_to_json
from data_migrations.template_migration.hpi import HPILoaderMixin

class HPILoader(HPILoaderMixin):
    """
        Load Note Data from Elation to Canvas as HPI command.

        Elation keeps track of Note Free Text data with categories. We will add create an HPI narrative
        by combining all the data for a specific note ID ordering by categories:

        Order of categories:
            Problem
            Reason
            Narrative
            ROS
            Past
            Allergies
            Med
            Family
            Social
            Habits
            PE
            Procedure
            Tx
            Assessment
            Instr
            Data
            Assessplan
            Test
            Followup

        It also produces multiple files:
        - The done_file keeps track of the Avon unique identifier to the canvas
          appointment id and patient key. This helps ensure no duplicate data is transfered and
          helps keep an audit of what was loaded.
        - The error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any data that may need manual fixing and replaying
        - The ignore file keeps track of any records that were skipped over
          during the ingest process potentially due to a patient not being
          in canvas, doctor not being in canvas, etc
        - The validation_error_file keeps track of all the Avon records that failed the validation of
          the Canvas Data Migration Template and why they failed
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'hpi'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.original_csv_file = 'PHI/Icon ShareFile Data (Updated) - NEW NOTES.csv'
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        # default needed for mapping
        self.default_location = "afad4e70-ca25-4a32-9f5c-2c83e2877b43"
        self.default_note_type_name = "Icon Historical Note"
        self.default_provider = "5eede137ecfe4124b8b773040e33be14"
        super().__init__(*args, **kwargs)

    def merge_data(self):

        if os.path.isfile(self.json_file):
            return fetch_from_json(self.json_file)

        data = defaultdict(list)

        with open(self.original_csv_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            print(reader.fieldnames)
            for row in reader:
                data[row['notes_data']].append(row)


        ordered_data = {}
        for _id, rows in data.items():
            categories = {
                "Problem": [],
                "Reason": [],
                "Narrative": [],
                "Hpi": [],
                "ROS": [],
                "Past": [],
                "Allergies": [],
                "Med": [],
                "Family": [],
                "Social": [],
                "Habits": [],
                "PE": [],
                "Procedure": [],
                "Tx": [],
                "Assessment": [],
                "Instr": [],
                "Data": [],
                "Assessplan": [],
                "Test": [],
                "Followup": [],
                "Surgical": [],
                "Orders": [],
            }
            for row in rows:
                categories.get(row['CATEGORY']).append((int(row['SEQUENCE']), row['TEXT']))

            ordered_data[_id] = {
                "Patient Identifier": row["PATIENT_ID"],
                "DOS": row["note_creation_time"],
                "categories": categories
            }

            
        write_to_json(self.json_file, ordered_data)

    def make_csv(self):

        if os.path.isfile(self.csv_file):
            return

        data = fetch_from_json(self.json_file)

        headers = {
            "ID",
            "Patient Identifier",
            "DOS",
            "Provider",
            "Location",
            "Note Type Name",
            "Narrative"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter="|")
            writer.writeheader()

            for _id, row in data.items():

                narrative = ""
                for category, text_list in row['categories'].items():
                    if not text_list:
                        continue
                    text_list.sort()
                    text = '\n'.join([i[1] for i in text_list])
                    narrative += f"{category}:\n{text}\n\n"

                writer.writerow({
                    "ID": _id,
                    "Patient Identifier": row['Patient Identifier'],
                    "DOS": arrow.get(row['DOS']).isoformat(),
                    "Provider": self.default_provider,
                    "Location": self.default_location,
                    "Note Type Name": self.default_note_type_name,
                    "Narrative": narrative
                })

        print("CSV successfully made")


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = HPILoader(environment="phi-iconhealth-test")
    #delimiter = ','
    # loader.merge_data()
    # loader.make_csv()

    # Validate the CSV values with the Canvas template data migration rules
    delimiter = '|'
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load_via_commands_api(valid_rows)
