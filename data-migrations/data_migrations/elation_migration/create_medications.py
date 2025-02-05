import csv, os
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows, write_to_json
from data_migrations.template_migration.medication import MedicationLoaderMixin

class MedicationLoader(MedicationLoaderMixin):
    """
        Load Appointments from Athena to Canvas. 

        Takes the CSV accomplish exported and converts the results into our templated CSV
        then loops through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

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
        self.data_type = 'medications'

        self.med_mapping_file = "mappings/medication_coding_map.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.original_csv_file = "PHI/Icon ShareFile Data (Updated) - NEW MEDS.csv"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map = fetch_from_json(self.note_map_file)
        self.med_mapping = fetch_from_json(self.med_mapping_file)

        # default needed for mapping
        self.default_location = "afad4e70-ca25-4a32-9f5c-2c83e2877b43"
        self.default_note_type_name = "Icon Data Migration"
        super().__init__(*args, **kwargs)

    def make_fdb_mapping(self, delimiter='|'):
        with open(self.original_csv_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                key = f"{row['DISPLAYED_MEDICATION_NAME']}|{row['CUI']}"
                if key not in self.med_mapping:
                    print(key)
                    self.med_mapping[key] = []

        write_to_json(self.med_mapping_file, self.med_mapping)

    def make_csv(self, delimiter='|'):
        """
            Fetch the Records from customer given file
            and convert into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        headers = {
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
            "Original Code"
        }

        # id,Patient_Id,DISPLAYED_MEDICATION_NAME,CUI,MEDICATION_TYPE,FULFILLMENT_TYPE


        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.original_csv_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    mapping_found = self.med_mapping.get(f"{row['DISPLAYED_MEDICATION_NAME']}|{row['CUI']}")

                    if mapping_found:
                        code = next(item['code'] for item in mapping_found if item["system"] == 'http://www.fdbhealth.com/')
                    else:
                        code = "unstructured"

                    writer.writerow({
                        "ID": row['id'],
                        "Patient Identifier": row['Patient_Id'],
                        "Status": "active",
                        "RxNorm/FDB Code": code,
                        "SIG": "",
                        "Medication Name": row['DISPLAYED_MEDICATION_NAME'],
                        "Original Code": row['CUI']
                    })

                print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = MedicationLoader(environment='phi-iconhealth-test')
    delimiter = ','

    # only run this if you need to create the mapping file for the first time
    #loader.make_fdb_mapping(delimiter=delimiter)
    #loader.map()

    # Make the Avon API call to their List Patients endpoint and convert the JSON return 
    # to the template CSV loader
    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    #loader.load(valid_rows, {"encounter_start_time": "2025-01-31"})

    loader.load_via_commands_api(valid_rows, note_kwargs={"encounter_start_time": "2025-01-31"})
