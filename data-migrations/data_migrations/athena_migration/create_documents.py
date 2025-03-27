import csv

from data_migrations.template_migration.document_reference import DocumentReferenceMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
)


class DocumentLoader(DocumentReferenceMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/documents/clinicaldocument.json"
        self.csv_file = "PHI/documents.csv"
        self.validation_error_file = "results/PHI/errored_document_validation.json"
        self.ignore_file = 'results/ignored_documents.csv'
        self.error_file_file = 'results/errored_documents.csv'
        self.done_file = "results/done_documents.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.fumage_helper = load_fhir_settings(environment)

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description",
            "Provider",
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in data:
                patient_id = row["patientdetails"]["fhir-patientid"].split("-")[-1]
                for document in row["clinicaldocuments"]:
                    row_to_write = {
                        "ID": document["clinicaldocumentid"],
                        "Patient Identifier": patient_id,
                        "Type": "34109-9",
                        "Clinical Date": document.get("observationdate", ""),
                        "Category": "uncategorizedclinicaldocument",
                        "Document": document.get("originaldocument", {}).get("reference", ""), # base64 encode these for upload;
                        "Description": document.get("documentdescription", ""),
                        "Provider": "" # TODO - add mapping to provider
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = DocumentLoader(environment="localhost")
    loader.make_csv()
    # valid_rows = loader.validate_as_csv(delimiter=",")
    # loader.load(valid_rows)

