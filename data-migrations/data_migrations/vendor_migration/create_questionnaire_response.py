import csv
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.questionnaire_response import QuestionnaireResponseLoaderMixin
from utils import VendorHelper

class QuestionnaireResponseLoader(QuestionnaireResponseLoaderMixin):
    """
    Load Questionnaire Responses from Vendor EMR to Canvas.
    
    Questionnaire responses include patient answers to clinical assessments and surveys.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'questionnaire_responses'

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

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """Fetch and transform questionnaire response data"""

        headers = {
            "ID",
            "Patient Identifier",
            "DOS",
            "Provider",
            "Location",
            "Note Type Name",
            "Note ID",
            "Note Title",
            "Questionnaire ID",
            "Questions"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            # TODO: Pick your option depending on your data source

            # If you are extracting data from your vendors API, you can make a 
            # helper class to perform the extraction
            # data = self.vendor_helper.fetch_questionnaire_responses()

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
            for response in data:

                writer.writerow({
                    "ID": response.get("id", ""),
                    "Patient Identifier": response.get("patient_identifier", ""),
                    "DOS": response.get("dos", ""),
                    "Provider": response.get("provider", ""),
                    "Location": response.get("location", ""),
                    "Note Type Name": response.get("note_type_name", ""),
                    "Note ID": response.get("note_id", ""),
                    "Note Title": response.get("note_title", ""),
                    "Questionnaire ID": "a13c5639-ebd4-472c-9527-4a6c4346ffd7",
                    "Questions": json.dumps({
                        "4e425e62-6f05-42c9-8dd2-e99d091b2905": [{"valueString": answer['response']}]
                    })
                })

        print("CSV successfully made")

if __name__ == '__main__':
    loader = QuestionnaireResponseLoader(environment='your-vendor-env')
    delimiter = ','
    
    # loader.make_csv(delimiter=delimiter)
    # valid_rows = loader.validate(delimiter=delimiter)
    # loader.load(valid_rows)
