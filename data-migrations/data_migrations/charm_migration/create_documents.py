from data_migrations.utils import fetch_from_json
from data_migrations.charm_migration.utils import CharmPatientAPI


class DocumentLoader:
    def __init__(self, environment) -> None:
        self.environment = environment
        self.json_file = "PHI/documents/documents.json"
        self.documents_files_dir = "PHI/documents/files/"

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


if __name__ == "__main__":
    loader = DocumentLoader(environment="ways2well")
    # loader.make_json()
    loader.get_document_types()
