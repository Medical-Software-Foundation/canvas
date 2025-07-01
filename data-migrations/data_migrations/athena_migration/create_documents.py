import arrow
import csv, json

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
        self.error_file = 'results/errored_documents.csv'
        self.done_file = "results/done_documents.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.temp_pdf_dir = "PHI/pdf_temp"
        self.documents_files_dir = "PHI/documents"
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
                patient_id = ""

                if "fhir-patientid" in row["patientdetails"]:
                    patient_id = row["patientdetails"]["fhir-patientid"].split("-")[-1]
                    assert patient_id == row["patientdetails"]["enterpriseid"]
                else:
                    patient_id = row["patientdetails"]["enterpriseid"]

                if not patient_id:
                    print(row)
                    raise ValueError("no patient ID")

                for document in row["clinicaldocuments"]:

                    original_document_path = document.get("originaldocument", {}).get("reference", "")

                    document_ref_list = None
                    if original_document_path:
                        document_ref_list = [original_document_path]

                    if not original_document_path and document.get("pages"):
                        pages = [(p["pageordering"], p["reference"],) for p in document["pages"]]
                        pages.sort()
                        document_ref_list = [p[1] for p in pages]

                    clinical_date = ""
                    observation_date = document.get("observationdate", "")
                    if observation_date:
                        clinical_date = arrow.get(observation_date, "MM/DD/YYYY").date().isoformat()

                    row_to_write = {
                        "ID": document["clinicaldocumentid"],
                        "Patient Identifier": patient_id,
                        "Type": "34109-9",
                        "Clinical Date": clinical_date,
                        "Category": "uncategorizedclinicaldocument",
                        "Document": json.dumps(document_ref_list) if document_ref_list else "",
                        "Description": document.get("documentdescription", ""),
                        "Provider": document.get("createduser", ""),
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")


if __name__ == "__main__":
    loader = DocumentLoader(environment="phi-test-accomplish")
    # loader.make_csv()
    valid_rows = loader.validate_as_csv(delimiter=",")
    loader.load(valid_rows)
