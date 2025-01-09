import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.patient import PatientLoaderMixin
from utils import AvonHelper

class PatientLoader(PatientLoaderMixin):
    """
        Load Patients from Avon to Canvas. 

        First makes the Avon List API call and converts the results into a CSV
        then loops through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

        It also produces multiple files:
        - The patient_map_file keeps track of the Avon unique identifier to the canvas patient key. 
          This allows for all other data types for data migration to be linked to the correct patient
        - The patient_error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any patients that may need manual fixing and replaying
        - The validation_error_file keeps track of all the Avon patients that failed the validation of 
          the Canvas Data Migration Template and why they failed
    """


    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = 'PHI/patients_valid.csv'
        self.validation_error_file = 'results/PHI/errored_patient_validation.json'
        self.error_file = 'results/PHI/errored_patients.csv'
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.avon_helper = AvonHelper(environment)

    def make_csv(self, delimiter='|'):
        """
            Fetch the Patient Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """

        data = self.avon_helper.fetch_records("v2/patients", param_string='')

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

        sex_map = {
            "248153007": "Male",
            "248152002": "Female",
            "261665006": "Unknown",
        }

        with open(self.patient_csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for patient in data:
                address = patient.get('addresses') or []
                writer.writerow({
                    "First Name": patient["first_name"],
                    "Middle Name": patient["middle_name"],
                    "Last Name": patient["last_name"],
                    "Date of Birth": patient["date_of_birth"],
                    "Sex at Birth": sex_map.get(patient["sex"]) or patient['gender'],
                    "Preferred Name": "",
                    "Address Line 1": address[0]['line1'] if address else '',
                    "Address Line 2": address[0]['line2'] if address else '',
                    "City": address[0]['city'] if address else '',
                    "State": address[0]['state'] if address else '',
                    "Postal Code": address[0]['postal_code'] if address else '',
                    "Country": 'us' if address else '',
                    "Mobile Phone Number": patient['phone'],
                    "Mobile Text Consent": True if patient['phone'] else False,
                    "Home Phone Number": "",
                    "Email": patient['email'],
                    "Email Consent": True if patient['email'] else False,
                    "Timezone": patient["timezone"],
                    "Clinical Note": "",
                    "Administrative Note": "",
                    "Identifier System 1": "Avon ID",
                    "Identifier Value 1": patient["id"],
                    "Identifier System 2": "Avon MRN",
                    "Identifier Value 2": patient["mrn"]
                })

            print("CSV successfully made")

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = PatientLoader(environment='phi-collaborative-test')
    delimiter = ','

    # Make the Avon API call to their List Patients endpoint and convert the JSON return 
    # to the template CSV loader
    loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, system_unique_identifier='Avon ID')
