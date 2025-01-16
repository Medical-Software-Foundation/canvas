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
        # self.patient_map_file = 'PHI/patient_id_map.json'
        # self.patient_map = fetch_from_json(self.patient_map_file)
        # self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.original_csv_file = "PHI/Icon ShareFile Data - medications.csv"
        self.csv_file = 'PHI/medications.csv'
        # self.ignore_file = 'results/ignored_appointments.csv'
        # self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        # self.validation_error_file = 'results/PHI/errored_appointment_validation.json'
        # self.error_file = 'results/errored_appointments.csv'
        # self.done_file = 'results/done_appointments.csv'
        # self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.med_mapping_file = "mappings/medication_coding_map.json"

    def make_fdb_mapping(self, delimiter='|'):
        mapping = {}
        with open(self.original_csv_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                mapping[f"{row['DISPLAYED_MEDICATION_NAME']}|{row['CUI']}"] = {}

        write_to_json(self.med_mapping_file, mapping)
        self.map(mapping)

    def make_csv(self, delimiter='|'):
        """
            Fetch the Records from customer given file
            and convert into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        headers = {
            "Unique ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
        }

        # id,Patient_Id,DISPLAYED_MEDICATION_NAME,CUI,MEDICATION_TYPE,FULFILLMENT_TYPE



        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.original_csv_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    writer.writerow({
                        "Unique ID": row['id'],
                        "Patient Identifier": row['Patient_Id'],
                        "Status": "",
                        "RxNorm/FDB Code": row['CUI'],
                        "SIG": "",
                        "Medication Name": row['DISPLAYED_MEDICATION_NAME'],
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
    loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    #valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    #loader.load(valid_rows, system_unique_identifier='avon', end_date_time_frame="2025-01-01")
