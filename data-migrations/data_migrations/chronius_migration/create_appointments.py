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
        self.data_type = 'appointments'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        # self.doctor_map = fetch_from_json("mappings/doctor_map.json")


        self.default_note_type = "chronius_data_migration"

    def make_csv(self, delimiter='|'):
        headers = [
            "ID",
            "Patient Identifier",
            "Appointment Type",
            "Appointment Type System",
            "Reason for Visit Code",
            "Reason for Visit Text",
            "Location",
            "Meeting Link",
            "Start Date / Time",
            "End Date/Time",
            "Duration",
            "Provider",
            "Status"
        ]

        # apptdate,apptdate,apptstarttime,apptendtime,apptid,apptstarttime,apptendtime,patient name,enterpriseid,appt schdlng prvdrid,apptstatus,appttype,svcdeptid,,,

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:

                    if row['Appointment Status'] in ('cancelled', 'noshow'):
                        self.ignore_row(row['ID'], f"Ignoring status {row['Appointment Status']}")
                        continue

                    if arrow.get(row['Start Date / Time']) < arrow.get("2025-07-20"):
                        continue

                    writer.writerow({
                        "ID": row['ID'],
                        "Patient Identifier": row['Patient Identifier'],
                        "Appointment Type": row['Appointment Type'],
                        "Appointment Type System": "http://snomed.info/sct",
                        "Reason for Visit Code": row['Reason for Visit Code'],
                        "Reason for Visit Text": "",
                        "Location": row["Location"],
                        "Meeting Link": row["Meeting Link"],
                        "Start Date / Time": row['Start Date / Time'],
                        "End Date/Time": row['End Date/Time'],
                        "Duration": row['Duration'] or "30",
                        "Provider": row['Provider'],
                        "Status": "booked"
                    })

                print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = AppointmentLoader(environment='chronius')
    delimiter = ','

    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, system_unique_identifier='chroniuscare', end_date_time_frame="")
