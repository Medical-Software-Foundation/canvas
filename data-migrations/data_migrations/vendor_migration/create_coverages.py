import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.coverage import CoverageLoaderMixin
from utils import VendorHelper

class CoverageLoader(CoverageLoaderMixin):
    """
    Load Coverages from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'coverages'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.payor_map_file = "mappings/payor_map.json"
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
        self.payor_map = fetch_from_json(self.payor_map_file)

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform coverage data"""
        
        headers = {
            "ID",
            "Patient Identifier",
            "Type",
            "Subscriber",
            "Member ID",
            "Relationship to Subscriber",
            "Coverage Start Date",
            "Payor ID",
            "Order",
            "Group Number",
            "Plan Name"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_coverages()

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
            for coverage in data:
                # Example of how to ignore rows that don't meet criteria:
                # if coverage.get("status") == "inactive":
                #     self.ignore_row(coverage.get("id", "unknown"), "Inactive coverage - skipping")
                #     continue

                # Payors are mapped to the payor_map.json file
                payor_id = self.payor_map.get(coverage.get("payor_name", ""), "")

                # Example of how to lookup subscribers when you have subscriber details:
                # subscriber_id = self.find_subscriber(
                #     first_name=coverage.get("subscriber_first_name"),
                #     last_name=coverage.get("subscriber_last_name"),
                #     dob=coverage.get("subscriber_dob"),
                #     name=coverage.get("subscriber_name")
                # )
                # 
                # if not subscriber_id:
                #     self.ignore_row(coverage.get("id", "unknown"), "Could not find subscriber")
                #     continue
                # 
                # subscriber = subscriber_id
                # 
                # Or if you already have the subscriber patient ID:
                subscriber = coverage.get("subscriber", "")

                writer.writerow({
                    "ID": coverage.get("id", ""),
                    "Patient Identifier": coverage.get("patient_identifier", ""),
                    "Type": coverage.get("type", ""),
                    "Subscriber": subscriber,
                    "Member ID": coverage.get("member_id", ""),
                    "Relationship to Subscriber": coverage.get("relationship_to_subscriber", ""),
                    "Coverage Start Date": coverage.get("coverage_start_date", ""),
                    "Payor ID": payor_id,
                    "Order": coverage.get("order", ""),
                    "Group Number": coverage.get("group_number", ""),
                    "Plan Name": coverage.get("plan_name", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = CoverageLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows, system_unique_identifier='Vendor Coverage ID')
