import csv, os
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows, write_to_json
from utils import AvonHelper

class CareTeam:
    """
        Load Care Team from Avon to Canvas. 

        First makes the Avon List API call and converts the results into a CSV
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
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = "PHI/care_team.json"
        self.csv_file = 'PHI/care_team.csv'
        # self.ignore_file = 'results/ignored_care_team.csv'
        # self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        # self.validation_error_file = 'results/PHI/errored_care_team_validation.json'
        # self.error_file = 'results/errored_care_team.csv'
        # self.done_file = 'results/done_care_team.csv'
        # self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.avon_helper = AvonHelper(environment)

        self.patient_name_map_file = 'PHI/patient_name_map.json'
        self.patient_name_map = self.make_patient_name_map()



    def make_patient_name_map(self):
        if os.path.isfile(self.patient_name_map_file):
            return fetch_from_json(self.patient_name_map_file)

        patients = fetch_from_json("PHI/patients.json")
        _map = {p['id']: f'{p["first_name"]} {p["last_name"]}'}
        write_to_json(_map, self.patient_name_map_file)


    def make_csv(self, delimiter='|'):
        """
            Fetch the Patient Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/care_teams", self.json_file, param_string='')

        # create a patient map
        

        # headers = {

        # }

        # with open(self.csv_file, 'w') as f:
        #     writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
        #     writer.writeheader()

        #     for row in data['data']:
        #         # skip over appointments that have been cancelled
        #         if row['status_history'][-1]['status'] == 'cancelled':
        #             self.ignore_row(row['id'], "Apt is cancelled")
        #             continue

        #         if len(row['attendees']) != 1:
        #             self.ignore_row(row['id'], "Attendees list does not contain only 1")
        #             continue

        #         patient = row['attendees'][0]['attendee']

        #         writer.writerow({

        #         })

        #     print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = CareTeam(environment='phi-collaborative-test')
    delimiter = '|'

    # Make the Avon API call to their List Patients endpoint and convert the JSON return 
    # to the template CSV loader
    loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    # loader.load(valid_rows, system_unique_identifier='avon', end_date_time_frame="2025-01-01")
