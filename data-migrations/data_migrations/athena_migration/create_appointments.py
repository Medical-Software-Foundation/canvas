import csv
import arrow

from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows
from data_migrations.template_migration.appointment import AppointmentLoaderMixin

class AppointmentLoader(AppointmentLoaderMixin):
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
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/provider_id_mapping.json")
        self.location_map_file = "mappings/location_map.json"
        self.location_map = fetch_from_json(self.location_map_file)
        self.original_csv_file = "PHI/athena_appointments.csv"
        self.csv_file = 'PHI/appointments.csv'
        self.ignore_file = 'results/ignored_appointments.csv'
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.validation_error_file = 'results/PHI/errored_appointment_validation.json'
        self.error_file = 'results/errored_appointments.csv'
        self.done_file = 'results/done_appointments.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.errored_note_state_event_file = 'results/errored_appointment_note_state_events.csv'

        # default needed for mapping
        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.default_note_type = "athena_historical_note"

    def make_csv(self, delimiter='|'):
        headers = [
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
        ]

        # apptdate,apptdate,apptstarttime,apptendtime,apptid,apptstarttime,apptendtime,patient name,enterpriseid,appt schdlng prvdrid,apptstatus,appttype,svcdeptid,,,

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.original_csv_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:

                    start_time = arrow.get(row['Start Date / Time'], "MM/DD/YYYY h:mm:ss A", tzinfo="US/Eastern").isoformat()
                    end_time = arrow.get(row['End Date/Time'], "MM/DD/YYYY h:mm:ss A", tzinfo="US/Eastern").isoformat()

                    writer.writerow({
                        "ID": row['Unique ID'],
                        "Patient Identifier": row['Patient Identifier'],
                        "Appointment Type": self.default_note_type,
                        "Reason for Visit Code": "",
                        "Reason for Visit Text": row['Appointment Type'],
                        "Location": row["Location"],
                        "Meeting Link": "",
                        "Start Date / Time": start_time,
                        "End Date/Time": end_time,
                        "Duration": row['Duration'],
                        "Provider": row['Provider']
                    })

                print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = AppointmentLoader(environment='phi-test-accomplish')
    delimiter = ','

    # Make the Avon API call to their List Patients endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, system_unique_identifier='athena', end_date_time_frame="2025-03-10")
