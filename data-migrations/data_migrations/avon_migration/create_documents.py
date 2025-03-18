import csv

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import (
    fetch_from_json,
    write_to_json,
    load_fhir_settings,
    fetch_from_csv,
    fetch_complete_csv_rows
)
from data_migrations.template_migration.utils import validate_date
from data_migrations.template_migration.hpi import HPILoaderMixin
from data_migrations.template_migration.plan import PlanLoaderMixin
from data_migrations.template_migration.document_reference import DocumentReferenceMixin

class DocumentLoader(DocumentReferenceMixin):
    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'documents'
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = f"PHI/{self.data_type}.json"
        self.template_json_file = f"PHI/template-{self.data_type}.json"
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

    def make_json(self):
        data = self.avon_helper.fetch_records(f"v2/{self.data_type}", self.json_file, param_string='')

        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description"
        ]

        ls = []
        for row in data:
            if row['type'] == 'pdf':
                document = self.avon_helper.fetch_resource(f"/v2/{self.data_type}/{row['id']}")

                file = document.get('file')
                if not file:
                    self.ignore_row(row["id"], "No PDF found")
                    continue

                ls.append({
                    "ID": row['id'],
                    "Patient Identifier": row['patient'],
                    "Type": "34109-9",
                    "Clinical Date": row['created_at'][:10],
                    "Category": "uncategorizedclinicaldocument",
                    "Document": file,
                    "Description": row['name']
                })

        write_to_json(self.template_json_file, ls)
        print("Successfully made templated JSON")

if __name__ == "__main__":
    loader = DocumentLoader(environment='phi-collaborative-test')

    #loader.make_json()
    valid_rows = loader.validate_as_json()
    loader.load(valid_rows)
