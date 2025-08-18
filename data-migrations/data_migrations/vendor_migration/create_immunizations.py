import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.immunization import ImmunizationLoaderMixin
from utils import VendorHelper

class ImmunizationLoader(ImmunizationLoaderMixin):
    """
    Load Immunizations from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'immunizations'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
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
        self.note_map = fetch_from_json(self.note_map_file)

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """
        Fetch the Immunization Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """

        headers = {
            "ID",
            "Patient Identifier",
            "Date Performed",
            "Immunization Text",
            "CVX Code",
            "Comment"
        }

        # TODO: Customize this mapping for your vendor's data format
        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_immunizations()

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
            for immunization in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not immunization.get("immunization_text"):
                #     self.ignore_row(immunization.get("id", "unknown"), "Missing immunization text - skipping")
                #     continue

                writer.writerow({
                    "ID": immunization.get("id", ""),
                    "Patient Identifier": immunization.get("patient_identifier", ""),
                    "Date Performed": immunization.get("date_performed", ""),
                    "Immunization Text": immunization.get("immunization_text", ""),
                    "CVX Code": immunization.get("cvx_code", ""),
                    "Comment": immunization.get("comment", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = ImmunizationLoader(environment='your-vendor-env')
    delimiter = ','
    
    # Step 1: Make the Vendor API call to their Immunizations endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # loader.load(valid_rows)
