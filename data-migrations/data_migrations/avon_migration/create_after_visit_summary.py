import csv, json

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import (
    fetch_from_json,
    write_to_json,
    load_fhir_settings,
    fetch_from_csv,
    fetch_complete_csv_rows
)
from data_migrations.template_migration.utils import validate_date
from data_migrations.template_migration.questionnaire_response import QuestionnaireResponseLoaderMixin

class AfterVisitSummaryLoader(QuestionnaireResponseLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'after_visit_summary'
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f"PHI/{self.data_type}.csv"
        self.ignore_file = f"results/ignored_{self.data_type}.csv"
        self.done_file = f'results/done_{self.data_type}.csv'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
        self.fumage_helper = load_fhir_settings(environment=environment)
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map = fetch_from_json(self.patient_map_file) 

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Historical Note"

    def make_csv(self, delimiter="|"):
        data = self.avon_helper.fetch_records(f"v2/documents", "PHI/documents.json", param_string='')

        headers = [
            "ID",
            "Patient Identifier",
            "DOS",
            "Provider",
            "Location",
            "Note Type Name",
            "Note ID",
            "Note Title",
            "Questionnaire ID",
            "Questions",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            #types {'incoming', 'template', 'pdf', 'image'}
            for row in data:
                if row['type'] == 'template':

                    for section in row['sections']:
                        if section['name'] != 'AVS':
                            self.ignore_row(row["id"], "Template not for AVS")

                        for answer in section['answers']:
                            if answer['response']:

                                provider = row["created_by"]
                                csv_row = {
                                    "ID": row['id'],
                                    "Patient Identifier": row['patient'],
                                    "DOS": row['created_at'],
                                    "Provider": "canvas-bot" if provider == 'user_null' else provider,
                                    "Location": self.default_location,
                                    "Note Type Name": self.default_note_type_name,
                                    "Note Title": "After Visit Summary",
                                    "Note ID": "",
                                    "Questionnaire ID": "a13c5639-ebd4-472c-9527-4a6c4346ffd7",
                                    "Questions": json.dumps({
                                        "4e425e62-6f05-42c9-8dd2-e99d091b2905": [{"valueString": answer['response']}]
                                    })
                                }

                                writer.writerow(csv_row)

        print("Successfully made CSV")


if __name__ == "__main__":
    loader = AfterVisitSummaryLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter=delimiter)
    loader.load(valid_rows)
