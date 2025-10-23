import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.patient import PatientLoaderMixin

class PatientLoader(PatientLoaderMixin):
    """
        Load Patients to Canvas.

        Loops through the CSV to validate the columns according to Canvas Data Migration Template
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
        self.original_csv_file = 'PHI/patient_diff.csv'
        self.csv_file = "PHI/patients.csv"
        self.validation_error_file = 'results/PHI/errored_patient_validation.json'
        self.error_file = 'results/PHI/errored_patients.csv'
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        # self.patient_map = fetch_from_json(self.patient_map_file)

    def make_csv(self, delimiter='|', csv_file=None, output_file=None):
        """
            Fetch the Patient Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """

        # looks like customer forgot the Home Phone Number column so just going to
        # add it as empty

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

        with open(output_file or self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(csv_file or self.original_csv_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    # if row['Identifier Value 1'] in self.patient_map:
                    #     continue

                    writer.writerow({
                        **row,
                        "Home Phone Number": ""
                    })

            print("CSV successfully made")

    def make_csv_diff(self, original_files, latest_file):

        KEY = "Identifier Value 1"
        headers = []

        original_file_map = {}
        for file in original_files:
            with open(file, 'r') as file1_reader:
                reader = csv.DictReader(file1_reader)
                headers = reader.fieldnames
                for row in reader:
                    key = row[KEY]

                    if key in original_file_map:
                        if original_file_map[key] == row:
                            continue
                        original_file_map[key] = row
                    else:
                        original_file_map[key] = row

        with open("PHI/patients_diff.csv", 'w') as f_diff:
            with open("PHI/patients_new.csv", 'w') as f_new:
                diff_writer = csv.DictWriter(f_diff, fieldnames=headers)
                diff_writer.writeheader()
                new_writer = csv.DictWriter(f_new, fieldnames=headers)
                new_writer.writeheader()

                with open(latest_file, 'r') as file2_reader:
                    reader = csv.DictReader(file2_reader)
                    for row in reader:
                        if found_record := original_file_map.get(row[KEY]):
                            if found_record != row:
                                diff_writer.writerow(row)
                        else:
                            new_writer.writerow(row)



if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = PatientLoader(environment='hellowisp')
    delimiter = ','

    # Make diff file
    #loader.make_csv_diff(original_files=['PHI/patients_july.csv', 'PHI/patients_sep.csv'], latest_file='PHI/patients_oct.csv')

    # Convert customer file to the template CSV loader
    loader.make_csv(delimiter=delimiter, csv_file="PHI/customer_patients_new_oct.csv", output_file="PHI/patients_new_oct.csv")

    # Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter, error_use_identifier='SWA patient ID')

    # If you are ready to load the rows that have passed validation to your Canvas instance
    #loader.load(valid_rows, system_unique_identifier='SWA patient ID')
