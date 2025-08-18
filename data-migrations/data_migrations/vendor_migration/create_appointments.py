import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.appointment import AppointmentLoaderMixin
from utils import VendorHelper

class AppointmentLoader(AppointmentLoaderMixin):
    """
    Load Appointments from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'appointments'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.appointment_map_file = "mappings/appointment_coding_map.json"
        self.reason_for_visit_map_file = "mappings/reason_for_visit_coding_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        # If you are extracting data from your vendors API, you can make a 
        # helper class to perform the extraction
        self.vendor_helper = VendorHelper(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.appointment_map = fetch_from_json(self.appointment_map_file)
        self.reason_for_visit_map = fetch_from_json(self.reason_for_visit_map_file)

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """
        Fetch the Appointment Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """

        headers = {
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
        }

        # TODO: Customize this mapping for your vendor's data format
        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_allergies()

            # If your data is in a JSON file, you can load it from the file
            # data = fetch_from_json(self.json_file)

            # If your data is already in a CSV file then loop through the 
            # file and map the data to the template format
            # data = []
            # with open(self.csv_file, 'r') as file:
            #     reader = csv.DictReader(file, delimiter=delimiter)
            #     for row in reader:
            #         data.append(row)
            
            # Below is mapping the data to the template format but you will need to 
            # address each column
            for appointment in data:
                # Example of how to ignore rows that don't meet criteria:
                # if appointment.get("status") == "cancelled":
                #     self.ignore_row(appointment.get("id", "unknown"), "Cancelled appointment - skipping")
                #     continue

                # For appointments, you will need to map the appointment type 
                appointment_type = self.appointment_map.get(appointment.get("appointment_type", ""), "historical")
                appointment_type_system = self.appointment_map.get(appointment.get("appointment_type", ""), "historical").get("system", "INTERNAL")

                # If you are using structured RFV, you will need to map the reason for visit code
                reason_for_visit_code = self.reason_for_visit_map.get(appointment.get("reason_for_visit_code", ""), "")

                writer.writerow({
                    "ID": appointment.get("id", ""),
                    "Patient Identifier": appointment.get("patient_identifier", ""),
                    "Appointment Type": appointment_type,
                    "Appointment Type System": appointment_type_system,
                    "Reason for Visit Code": reason_for_visit_code,
                    "Reason for Visit Text": appointment.get("reason_for_visit_text", ""),
                    "Location": appointment.get("location", ""),
                    "Meeting Link": appointment.get("meeting_link", ""),
                    "Start Date / Time": appointment.get("start_date_time", ""),
                    "End Date/Time": appointment.get("end_date_time", ""),
                    "Duration": appointment.get("duration", ""),
                    "Provider": appointment.get("provider", ""),
                    "Status": appointment.get("status", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = AppointmentLoader(environment='your-vendor-env')
    delimiter = ','
    
    # Step 1: Make the Vendor API call to their Appointments endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # Optionally add end_date_time_frame to skip future appointments
    # loader.load(valid_rows, end_date_time_frame='2024-01-01')
