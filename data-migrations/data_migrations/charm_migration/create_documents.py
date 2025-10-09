import csv, json, os

from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.document_reference import DocumentReferenceMixin


class DocumentLoader(DocumentReferenceMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.json_file = "PHI/documents/documents.json"
        self.csv_file = "PHI/documents/documents.csv"
        self.documents_files_dir = "PHI/documents/files_temp"
        self.document_type_mapping_file = "mappings/document_type_mapping.json"
        self.document_type_mapping = fetch_from_json(self.document_type_mapping_file)
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.done_file = 'results/done_documents.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_documents.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_documents.csv'
        self.fumage_helper = load_fhir_settings(environment)

    def make_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]
        charm_patient_api.fetch_documents(patient_ids, self.json_file, self.documents_files_dir)

    def get_document_types(self):
        document_types = []
        data = fetch_from_json(self.json_file)
        for patient_id, file_list in data.items():
            for f in file_list:
                file_type = f["file_type"]
                if file_type not in document_types:
                    document_types.append(file_type)
        for document_type in document_types:
            print(document_type)

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description",
            "Comment",
            "Provider",
        ]
        data = fetch_from_json(self.json_file)
        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(fhandle, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for patient_id, documents in data.items():
                for doc in documents:
                    doc_mapping = self.document_type_mapping[doc["file_type"]]
                    if doc_mapping["type"] == "Diagnostic Report":
                        self.ignore_row(doc["file_id"], "Ignoring because needs to be imported as a Diagnostic Report")
                        continue
                    if not doc["file_name"].lower().endswith(".pdf"):
                        self.ignore_row(doc["file_id"], "Ignoring because not a PDF file")
                        continue
                    file_name_split = doc["file_name"].split(".")
                    file_name_without_extension = "".join(file_name_split[:-1])
                    row_to_write = {
                        "ID": doc["file_id"],
                        "Patient Identifier": doc["patient_id"],
                        "Type": doc_mapping["type"],
                        "Clinical Date": doc["date"],
                        "Category": doc_mapping["category"],
                        "Document": doc["file_id"], # fetch file during import
                        "Description": file_name_without_extension,
                        "Comment": "",
                        "Provider": "",
                    }
                    writer.writerow(row_to_write)
        print(f"Successfully created {self.csv_file}")

    def fetch_file_and_get_base64_string(self, charm_patient_api_instance, patient_id, file_id):
        temp_file_path = f"{self.documents_files_dir}/{file_id}.pdf"
        file_bytes = charm_patient_api_instance.fetch_file(patient_id, file_id)
        with open(temp_file_path, "wb") as fhandle:
            fhandle.write(file_bytes)
        base_64_str = self.base64_encode_file(temp_file_path)
        os.remove(temp_file_path)
        return base_64_str

    def load(self, validated_rows, note_kwargs={}):
        charm_patient_api = CharmPatientAPI(environment=self.environment)

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            b64_document_string = self.fetch_file_and_get_base64_string(
                charm_patient_api,
                row['Patient Identifier'],
                row["Document"],
            )

            payload = {
                "resourceType": "DocumentReference",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
                        "valueDate": row['Clinical Date']
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-review-mode",
                        "valueCode": "RN"
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-reviewer",
                        "valueReference": {
                            "reference": "Practitioner/5eede137ecfe4124b8b773040e33be14",
                        }
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-priority",
                        "valueBoolean": False
                    },
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/document-reference-requires-signature",
                        "valueBoolean": False
                    }
                ],
                "status": "current",
                "type": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": row['Type']
                        }
                    ]
                },
                "description": row['Description'],
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://schemas.canvasmedical.com/fhir/document-reference-category",
                                "code": row['Category']
                            }
                        ]
                    }
                ],
                "subject": {
                    "reference": f"Patient/{patient_key}",
                    "type": "Patient"
                },
                "content": [
                    {
                        "attachment": {
                            "contentType": "application/pdf",
                            "data": b64_document_string
                        }
                    }
                ]
            }

            if row['Comment']:
                payload['extension'].append({
                    "url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
                    "valueString": row['Comment']
                })

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)


if __name__ == "__main__":
    loader = DocumentLoader(environment="ways2well")
    # loader.make_json()
    # loader.get_document_types()
    # loader.make_csv()
    valid_rows = loader.validate_as_csv(delimiter=",")
    loader.load(valid_rows)
