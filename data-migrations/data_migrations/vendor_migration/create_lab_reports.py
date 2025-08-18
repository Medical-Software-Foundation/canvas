import csv, json
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.lab_report import LabReportLoaderMixin
from utils import VendorHelper

class LabReportLoader(LabReportLoaderMixin):
    """
    Load Lab Reports from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'lab_reports'

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
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        self.documents_files_dir = "PHI/lab_reports"

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform lab report data"""

        headers = {
            "ID",
            "Patient Identifier",
            "Lab Date",
            "Document",
            "Lab Test Name",
            "Lab LOINC Code"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_lab_reports()

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
            for lab_report in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not lab_report.get("document"):
                #     self.ignore_row(lab_report.get("id", "unknown"), "Missing lab report document - skipping")
                #     continue

                # The Document field should contain the file name if the given self.documents_files_dir folder
                document_filename = lab_report.get("document", "")

                writer.writerow({
                    "ID": lab_report.get("id", ""),
                    "Patient Identifier": lab_report.get("patient_identifier", ""),
                    "Lab Date": lab_report.get("lab_date", ""),
                    "Document": json.dumps([document_filename]),
                    "Lab Test Name": lab_report.get("lab_test_name", ""),
                    "Lab LOINC Code": lab_report.get("lab_loinc_code", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = LabReportLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
