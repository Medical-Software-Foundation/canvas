import csv, os, json
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows
from data_migrations.template_migration.appointment import AppointmentLoaderMixin
from data_migrations.avon_migration.utils import CalComHelper


class FutureAppointmentLoader(AppointmentLoaderMixin):
    """
        Load Appointments from Avon to Canvas.

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
        self.data_type = "future_appointments"
        self.patient_map_file = 'PHI/patient_email_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.cal_com_helper = CalComHelper(environment)

        # default needed for mapping
        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type = "avon_historical_note"

    def make_patient_map_with_emails(self):

        search_parameters = {
            '_sort': 'pk',
            '_count': 100,
            '_offset': 0,
        }

        patients = {}
        while True:
            response = self.fumage_helper.search("Patient", search_parameters)

            if response.status_code != 200:
                raise Exception(f"Failed to perform {response.url}. \n Fumage Correlation ID: {response.headers['fumage-correlation-id']} \n {response.text}")

            print(f'Performed search with url: {response.url}')
            response_json = response.json()
            for item in response_json['entry']:
                resource = item['resource']
                email = next((t['value'] for t in resource['telecom'] if t['system'] == 'email'), None)
                if email:
                    patients[email] = resource['id']

            _next = any([l['relation'] == 'next' for l in response_json['link']])
            if not _next:
                break
            search_parameters['_offset'] = search_parameters['_offset'] + search_parameters['_count']

        with open(self.patient_map_file, 'w', encoding='utf-8') as f:
            json.dump(patients, f, ensure_ascii=False, indent=4)

    def make_csv(self, delimiter='|'):
        """
            Fetch the Appointment Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.cal_com_helper.fetch_records("v2/bookings", self.json_file, param_string='afterStart=2025-02-26')

        headers = {
            "ID",
            "Patient Identifier",
            "Appointment Type",
            "Reason for Visit Code",
            "Reason for Visit Text",
            "Location",
            "Meeting Link",
            "Start Date / Time",
            "End Date/Time",
            "Duration",
            "Provider"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                # skip over appointments that have been cancelled
                if row['status'] == 'cancelled':
                    self.ignore_row(row['id'], "Apt is cancelled")
                    continue

                if len(row['attendees']) != 1:
                    self.ignore_row(row['id'], "Attendees list does not contain only 1")
                    continue

                writer.writerow({
                    "ID": row.get('uid'),
                    "Patient Identifier": row['bookingFieldsResponses']['email'],
                    "Appointment Type": "fu_telehealth" if row['eventType']['slug'].lower().startswith("follow-up") else "new_telehealth",
                    "Reason for Visit Code": "",
                    "Reason for Visit Text": row['title'],
                    "Location": self.default_location,
                    "Meeting Link": row.get('meetingUrl') or "",
                    "Start Date / Time": row['start'],
                    "End Date/Time": row['end'],
                    "Duration": "",
                    "Provider": row['hosts'][0]['email']
                })

            print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = FutureAppointmentLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_patient_map_with_emails()

    # Make the Avon API call to their List Appointments endpoint and convert the JSON return
    # to the template CSV loader
    loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    #valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    #loader.load(valid_rows, system_unique_identifier='avon', end_date_time_frame="2025-02-20")
