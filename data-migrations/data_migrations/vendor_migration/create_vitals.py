import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.vitals import VitalsLoaderMixin
from utils import VendorHelper

class VitalsLoader(VitalsLoaderMixin):
    """
    Load Vitals from Vendor EMR to Canvas.
    
    Vitals include blood pressure, temperature, pulse, etc.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'vitals'

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
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform vitals data"""

        headers = {
            "id",
            "patient",
            "height",
            "weight_lbs",
            "body_temperature",
            "blood_pressure_systole",
            "blood_pressure_diastole",
            "pulse",
            "respiration_rate",
            "oxygen_saturation",
            "created_by",
            "created_at",
            "comment"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_vitals()

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
            for vital in data:
                # Example of how to ignore rows that don't meet criteria:
                # if not vital.get("value_quantity"):
                #     self.ignore_row(vital.get("id", "unknown"), "Missing vital value - skipping")
                #     continue
                writer.writerow({
                    "id": vital.get("id", ""),
                    "patient": vital.get("patient", ""),
                    "height": vital.get("height", ""),
                    "weight_lbs": vital.get("weight_lbs", ""),
                    "body_temperature": vital.get("body_temperature", ""),
                    "blood_pressure_systole": vital.get("blood_pressure_systole", ""),
                    "blood_pressure_diastole": vital.get("blood_pressure_diastole", ""),
                    "pulse": vital.get("pulse", ""),
                    "respiration_rate": vital.get("respiration_rate", ""),
                    "oxygen_saturation": vital.get("oxygen_saturation", ""),
                    "created_by": vital.get("created_by", ""),
                    "created_at": vital.get("created_at", ""),
                    "comment": vital.get("comment", "")
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = VitalsLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
