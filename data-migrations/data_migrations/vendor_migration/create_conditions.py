import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.condition import ConditionLoaderMixin
from utils import VendorHelper
from data_migrations.template_migration.mapping_review import ConditionReview

class ConditionLoader(ConditionLoaderMixin, ConditionReview):
    """
    Load Conditions from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'conditions'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.condition_map_file = "mappings/condition_coding_map.json"
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
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.condition_map = fetch_from_json(self.condition_map_file)

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def create_condition_map(self):
        """
        Create the condition map from the data source and save it to the condition_map_file
        The key of the map should be the condition text and the icd10 code separated by a pipe
        """
        condition_map = fetch_from_json(self.condition_map_file)

        # TODO: Pick your option depending on your data source

        # If you are extracting data from your vendors API, you can make a 
        # helper class to perform the extraction
        # data = self.vendor_helper.fetch_conditions()

        # If your data is in a JSON file, you can load it from the file
        # data = fetch_from_json(self.json_file)

        # If your data is already in a CSV file then loop through the 
        # file and map the data to the template format
        # data = []
        # with open(self.csv_file, 'r') as file:
        #     reader = csv.DictReader(file, delimiter=delimiter)
        #     for row in reader:
        #         data.append(row)

        for condition in data:
            condition_text = condition.get("name", "")
            condition_icd10_code = condition.get("icd10_code", "")

            mapping_key = f"{condition_text}|{condition_icd10_code}"

            if mapping_key in self.condition_map:
                continue

            condition_map[mapping_key] = []

        write_to_json(self.condition_map_file, condition_map)


    def make_csv(self, delimiter='|'):
        """
        Fetch the Condition Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """

        headers = {
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "ICD-10 Code",
            "Onset Date",
            "Free text notes",
            "Resolved Date",
            "Recorded Provider",
            "Name"
        }

        # TODO: Customize this mapping for your vendor's data format
        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_conditions()

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
            for condition in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not condition.get("icd10_code"):
                #     self.ignore_row(condition.get("id", "unknown"), "Missing ICD-10 code - skipping")
                #     continue

                # to map the ICD-10 code, you will need to map the name and code to the condition_map
                icd10_code = self.condition_map.get(condition.get("name", {})).get("code", "")
                icd10_display = self.condition_map.get(condition.get("name", {})).get("display", "")

                writer.writerow({
                    "ID": condition.get("id", ""),
                    "Patient Identifier": condition.get("patient_identifier", ""),
                    "Clinical Status": condition.get("clinical_status", ""),
                    "ICD-10 Code": icd10_code,
                    "Onset Date": condition.get("onset_date", ""),
                    "Free text notes": condition.get("free_text_notes", ""),
                    "Resolved Date": condition.get("resolved_date", ""),
                    "Recorded Provider": condition.get("recorded_provider", ""),
                    "Name": icd10_display
                })

        print("CSV successfully made")

if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = ConditionLoader(environment='your-vendor-env')
    delimiter = ','

    # Create the condition map from the unique set of conditions found in the data source
    # loader.create_condition_map()

    # Now that the condition map is created, you can use the `map` function to search for the 
    # condition text/icd10 code and map the data to the template format
    # loader.map()

    # After the search has been complete, there will be some items that need manual review and decisions        
    # to map the condition to the correct coding. 
    # loader.review()
    
    # Step 1: Make the Vendor API call to their Conditions endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # loader.load(valid_rows)
