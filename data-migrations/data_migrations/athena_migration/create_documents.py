import csv

from data_migrations.template_migration.document_reference import DocumentReferenceMixin
from data_migrations.utils import fetch_from_json


class DocumentLoader(DocumentReferenceMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/documents/clinicaldocument.json"
        self.csv_file = "PHI/documents.csv"

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description"
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in data:
                patient_id = row["patientdetails"]["fhir-patientid"]
                for document in row["clinicaldocuments"]:

                    row_to_write = {
                        "ID": document["clinicaldocumentid"],
                        "Patient Identifier": patient_id,
                        "Type": "34109-9",
                        "Clinical Date": document.get("observationdate", ""),
                        "Category": "uncategorizedclinicaldocument",
                        "Document": document.get("originaldocument", {}).get("reference", ""), # base64 encode these for upload;
                        "Description": document.get("documentdescription", "")
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = DocumentLoader(environment="localhost")
    loader.make_csv()
