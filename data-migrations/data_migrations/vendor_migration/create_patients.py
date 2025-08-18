import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.patient import PatientLoaderMixin
from utils import VendorHelper

class PatientLoader(PatientLoaderMixin):
    """
    Load Patients from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'patients'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
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
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """
        Fetch the Patient Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """
        
        headers = {
            "First Name",
            "Middle Name",
            "Last Name",
            "Date of Birth",
            "Sex at Birth",
            "Preferred Name",
            "Address Line 1",
            "Address Line 2",
            "City",
            "State",
            "Postal Code",
            "Country",
            "Mobile Phone Number",
            "Mobile Text Consent",
            "Home Phone Number",
            "Email",
            "Email Consent",
            "Timezone",
            "Clinical Note",
            "Administrative Note",
            "Identifier System 1",
            "Identifier Value 1",
            "Identifier System 2",
            "Identifier Value 2"
        }

        # TODO: Customize this mapping for your vendor's data format
        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_patients()

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
            for patient in data:
                writer.writerow({
                    "First Name": patient.get("first_name", ""),
                    "Middle Name": patient.get("middle_name", ""),
                    "Last Name": patient.get("last_name", ""),
                    "Date of Birth": patient.get("date_of_birth", ""),
                    "Sex at Birth": patient.get("sex_at_birth", ""),
                    "Preferred Name": patient.get("preferred_name", ""),
                    "Address Line 1": patient.get("address_line_1", ""),
                    "Address Line 2": patient.get("address_line_2", ""),
                    "City": patient.get("city", ""),
                    "State": patient.get("state", ""),
                    "Postal Code": patient.get("postal_code", ""),
                    "Country": patient.get("country", ""),
                    "Mobile Phone Number": patient.get("mobile_phone_number", ""),
                    "Mobile Text Consent": patient.get("mobile_text_consent", ""),
                    "Home Phone Number": patient.get("home_phone_number", ""),
                    "Email": patient.get("email", ""),
                    "Email Consent": patient.get("email_consent", ""),
                    "Timezone": patient.get("timezone", ""),
                    "Clinical Note": patient.get("clinical_note", ""),
                    "Administrative Note": patient.get("administrative_note", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = PatientLoader(environment='your-vendor-env')
    delimiter = ','
    
    # Step 1: Make the Vendor API call to their Patients endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # You want to pass the Identifier System that we will be using to ensure patients are not duplicated
    # loader.load(valid_rows, system_unique_identifier='Vendor ID')
