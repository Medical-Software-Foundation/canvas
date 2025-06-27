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
        self.json_file = "PHI/encounterdocument.json"
        self.csv_file = "PHI/encounter_documents.csv"
        self.validation_error_file = "results/PHI/errored_encounter_document_validation.json"
        self.ignore_file = 'results/ignored_encounter_documents.csv'
        self.error_file = 'results/errored_encounter_documents.csv'
        self.done_file = "results/done_encounter_documents.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.temp_pdf_dir = "PHI/pdf_temp"
        self.documents_files_dir = "PHI/encounter_documents"
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
                patient_id = row["patientdetails"]["enterpriseid"]
                for document in row["encounterdocuments"]:
                    document_date = ""
                    encounter_date = document.get("encounterdate", "")
                    if encounter_date:
                        document_date = arrow.get(encounter_date, "MM/DD/YYYY").date().isoformat()

                    pages = [(int(p["pageordering"]), p["reference"],) for p in document["pages"]]
                    pages.sort()
                    document_ref_list = [p[1] for p in pages]

                    row_to_write = {
                        "ID": document["encounterdocumentid"],
                        "Patient Identifier": patient_id,
                        "Type": "51851-4",
                        "Clinical Date": document_date,
                        "Category": "patientadministrativedocument",
                        "Document": json.dumps(document_ref_list) if document_ref_list else "",
                        "Description": document.get("description", ""),
                        "Provider": document.get("providerusername", ""),
                    }
                    writer.writerow(row_to_write)
        print("CSV successfully made")

if __name__ == "__main__":
    loader = DocumentLoader(environment="phi-test-accomplish")
    # loader.make_csv()
    valid_rows = loader.validate_as_csv(delimiter=",")
    loader.load(valid_rows)
