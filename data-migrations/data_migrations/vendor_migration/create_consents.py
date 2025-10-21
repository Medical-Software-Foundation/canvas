import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.consent import ConsentLoaderMixin
from utils import VendorHelper

class ConsentLoader(ConsentLoaderMixin):
    """
    Load Consents from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'consents'

        self.patient_map_file = 'PHI/patient_id_map.json'
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
        self.documents_dir = "PHI/consent_documents"

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform consent data"""

        headers = {
            "ID",
            "Patient Identifier",
            "Status",
            "Code",
            "Start Date",
            "End Date",
            "Document"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_consents()

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
            for consent in data:
                # Example of how to ignore rows that don't meet criteria:
                # if consent.get("status") == "rejected":
                #     self.ignore_row(consent.get("id", "unknown"), "Rejected consent - skipping")
                #     continue

                writer.writerow({
                    "ID": consent.get("id", ""),
                    "Patient Identifier": consent.get("patient_identifier", ""),
                    "Status": consent.get("status", ""),
                    "Code": consent.get("code", ""),
                    "Start Date": consent.get("start_date", ""),
                    "End Date": consent.get("end_date", ""),
                    "Document": consent.get("path_to_document", ""),
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = ConsentLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
