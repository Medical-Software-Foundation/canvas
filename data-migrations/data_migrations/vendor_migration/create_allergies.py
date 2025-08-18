import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.allergy import AllergyLoaderMixin
from data_migrations.template_migration.mapping_review import AllergyReview
from utils import VendorHelper

class AllergyLoader(AllergyLoaderMixin, AllergyReview):
    """
    Load Allergies from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'allergies'

        # Mapping files
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.allergy_map_file = "mappings/allergy_coding_map.json"

        # PHI files
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'

        # Result files
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
        self.allergy_map = fetch_from_json(self.allergy_map_file)

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def create_allergy_map(self):
        """
        Create the allergy map from the data source and save it to the allergy_map_file
        The key of the map should be the allergy text and the rxnorm code separated by a pipe
        """
        allergy_map = fetch_from_json(self.allergy_map_file)

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

        for allergy in data:
            allergy_text = allergy.get("name", "")
            allergy_rxnorm_code = allergy.get("rxnorm_code", "")

            mapping_key = f"{allergy_text}|{allergy_rxnorm_code}"

            if mapping_key in self.allergy_map:
                continue

            allergy_map[mapping_key] = []

        write_to_json(self.allergy_map_file, allergy_map)

    def make_csv(self, delimiter='|'):
        """Fetch and transform allergy data
        
        Use the different options to transform the data into the template format for ease
        """


        headers = {
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider",
            "Severity",
            "Original Name"
        }

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
            for allergy in data:
                # Example of how to ignore rows that don't meet criteria:
                # if allergy.get("status") == "inactive":
                #     self.ignore_row(allergy.get("id", "unknown"), "Inactive allergy - skipping")
                #     continue

                # To ingest allergies in Canvas, you need an FDB code
                # read more about this in the README file 
                fdb_code = self.allergy_map.get(allergy.get("name", "")).get("code", "1-143")
                fdb_display = self.allergy_map.get(allergy.get("name", "")).get("display", "No Allergy Information Available")

                writer.writerow({
                    "ID": allergy.get("id", ""),
                    "Patient Identifier": allergy.get("patient_identifier", ""),
                    "Clinical Status": allergy.get("clinical_status", ""),
                    "Type": allergy.get("type", ""),
                    "FDB Code": fdb_code,
                    "Name": fdb_display,
                    "Onset Date": allergy.get("onset_date", ""),
                    "Free Text Note": allergy.get("free_text_note", ""),
                    "Reaction": allergy.get("reaction", ""),
                    "Recorded Provider": allergy.get("recorded_provider", ""),
                    "Severity": allergy.get("severity", ""),

                     # only set this if you want the original name from the current EMR to be displayed in the command
                    "Original Name": allergy.get("name", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = AllergyLoader(environment='your-vendor-env')
    delimiter = ','

    # Create the allergy map from the unique set of allergies found in the data source
    # loader.create_allergy_map()

    # Now that the allergy map is created, you can use the `map` function to search for the 
    # allergy text/rxnorm code and map the data to the template format
    # loader.map()

    # After the search has been complete, there will be some items that need manual review and decisions        
    # to map the allergy to the correct coding. 
    # loader.review()


    # Now that the allergy map is created, you can use the `make_csv` function to make the CSV file
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)

    # Allergies are loaded through the FHIR AllergyIntolerance endpoint
    # loader.load(valid_rows)
