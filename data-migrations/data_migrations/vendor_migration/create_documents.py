import csv, json
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.document_reference import DocumentReferenceLoaderMixin
from utils import VendorHelper

class DocumentLoader(DocumentReferenceLoaderMixin):
    """
    Load Documents from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'documents'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.document_map_file = "mappings/document_coding_map.json"
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
        self.document_map = fetch_from_json(self.document_map_file)

        self.documents_files_dir = "PHI/documents"

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform document data"""

        headers = {
            "ID",
            "Patient Identifier",
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description",
            "Comment",
            "Provider"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_documents()

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
            for document in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not document.get("document"):
                #     self.ignore_row(document.get("id", "unknown"), "Missing document file - skipping")
                #     continue

                # The Document field should contain the file name if the given self.documents_files_dir folder
                document_filename = document.get("document", "")

                writer.writerow({
                    "ID": document.get("id", ""),
                    "Patient Identifier": document.get("patient_identifier", ""),
                    "Type": document.get("type", ""),
                    "Clinical Date": document.get("clinical_date", ""),
                    "Category": document.get("category", ""),
                    "Document": json.dumps([document_filename]),
                    "Description": document.get("description", ""),
                    "Comment": document.get("comment", ""),
                    "Provider": document.get("provider", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = DocumentLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
