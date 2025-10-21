import csv, arrow
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.template_migration.mapping_review import MedicationReview
from utils import VendorHelper

class MedicationLoader(MedicationLoaderMixin, MedicationReview):
    """
    Load Medications from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'medications'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.medication_map_file = "mappings/medication_coding_map.json"
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
        self.medication_map = fetch_from_json(self.medication_map_file)

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def create_medication_map(self):
        """
        Create the medication map from the data source and save it to the medication_map_file
        The key of the map should be the medication text and the rxnorm code separated by a pipe
        """
        medication_map = fetch_from_json(self.medication_map_file)

        # TODO: Pick your option depending on your data source

        # If you are extracting data from your vendors API, you can make a 
        # helper class to perform the extraction
        # data = self.vendor_helper.fetch_medications()

        # If your data is in a JSON file, you can load it from the file
        # data = fetch_from_json(self.json_file)

        # If your data is already in a CSV file then loop through the 
        # file and map the data to the template format
        # data = []
        # with open(self.csv_file, 'r') as file:
        #     reader = csv.DictReader(file, delimiter=delimiter)
        #     for row in reader:
        #         data.append(row)

        for medication in data:
            medication_text = medication.get("name", "")
            medication_rxnorm_code = medication.get("rxnorm_code", "")

            mapping_key = f"{medication_text}|{medication_rxnorm_code}"

            if mapping_key in self.medication_map:
                continue

            medication_map[mapping_key] = []

        write_to_json(self.medication_map_file, medication_map)


    def make_csv(self, delimiter='|'):
        """
        Fetch the Medication Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """

        headers = {
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
            "Original Code",
            "Start Date",
            "End Date"
        }

        # TODO: Customize this mapping for your vendor's data format
        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_medications()

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
            for medication in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not medication.get("medication_name"):
                #     self.ignore_row(medication.get("id", "unknown"), "Missing medication name - skipping")
                #     continue

                # Medications can be ingested as unstructured or FDB
                medication_name = medication.get("medication_name", "")
                mapping_found = self.medication_map.get(f"{medication_name}|{medication.get('original_code', '')}".lower())

                if mapping_found:
                    code = mapping_found['code']
                    display = mapping_found['display']
                else:
                    code = "unstructured"
                    display = medication_name

                writer.writerow({
                    "ID": medication.get("id", ""),
                    "Patient Identifier": medication.get("patient_identifier", ""),
                    "Status": medication.get("status", ""),
                    "RxNorm/FDB Code": code,
                    "SIG": medication.get("sig", ""),
                    "Medication Name": display,
                    "Original Code": medication.get("original_code", ""),

                    # TODO: Convert the start and end dates to the Canvas date format
                    "Start Datetime": arrow.get(medication.get("start_datetime", "")).isoformat(),
                    "End Datetime": arrow.get(medication.get("end_datetime", "")).isoformat()
                })

        print("CSV successfully made")

if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = MedicationLoader(environment='your-vendor-env')
    delimiter = ','

    # Create the medication map from the unique set of medications found in the data source
    # loader.create_medication_map()

    # Now that the medication map is created, you can use the `map` function to search for the 
    # medication text/rxnorm code and map the data to the template format
    # loader.map()

    # After the search has been complete, there will be some items that need manual review and decisions        
    # to map the medication to the correct coding. 
    # loader.review()
    
    # Step 1: Make the Vendor API call to their Medications endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_csv(delimiter=delimiter)
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # loader.load(valid_rows)
