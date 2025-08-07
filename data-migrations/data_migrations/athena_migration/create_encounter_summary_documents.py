import arrow, os, csv, json

from data_migrations.template_migration.document_reference import DocumentReferenceMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
)


class DocumentLoader(DocumentReferenceMixin):
    def __init__(self, environment, *args, **kwargs):
        data_type = "encountersummary"
        self.environment = environment
        self.json_file = f"PHI/{data_type}.json"
        self.csv_file = f"PHI/{data_type}_documents.csv"
        self.validation_error_file = f"results/PHI/errored_{data_type}_document_validation.json"
        self.ignore_file = f'results/ignored_{data_type}_documents.csv'
        self.error_file = f'results/errored_{data_type}_documents.csv'
        self.done_file = f"results/done_{data_type}_documents.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.temp_pdf_dir = "PHI/pdf_temp"
        self.documents_files_dir = "PHI"
        self.fumage_helper = load_fhir_settings(environment)

    def make_csv(self):

        """
            "appointmentid": "208483",
            "appointmentstartdate": "2024-10-30T14:45:00-04:00",
            "departmentid": "17",
            "providerid": "14",
            "isclosing": "true",
            "status": "CLOSED",
            "providerphone": "(888) 662-4421",
            "providerfirstname": "Michael",
            "reference": "/encountersummary_files/encountersummary_94541.html",
            "lastreopened": "02/08/2025",
            "encounterid": "94541",
            "encounterdate": "10/30/2024",
            "closeduser": "malbert32",
            "patientstatus": "Checked Out",
            "lastupdated": "02/08/2025",
            "providerlastname": "Albert",
            "encountertype": "VISIT",
            "chartid": "2606",
            "encountervisitname": "Follow Up Clinician Visit",
            "patientstatusid": "4",
            "closeddate": "2025-02-08T14:49:21-05:00
        """

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
                for document in row["encountersummary"]:
                    document_date = ""
                    encounter_date = document.get("encounterdate", "")
                    if encounter_date:
                        document_date = arrow.get(encounter_date, "MM/DD/YYYY").date().isoformat()

                    if not document['reference']:
                        self.ignore_row(document["encounterid"], f"File missing")
                        continue
                    document_file = document['reference']
                    pdf_file_path = document_file.replace('.html', '.pdf')

                    if os.path.isfile(pdf_file_path):
                        document_file = pdf_file_path

                    row_to_write = {
                        "ID": document["encounterid"],
                        "Patient Identifier": patient_id,
                        "Type": "11503-0",
                        "Clinical Date": document_date,
                        "Category": "uncategorizedclinicaldocument",
                        "Document": json.dumps([document_file]),
                        "Description": document.get("encountervisitname", ""),
                        "Provider": document.get("closeduser", ""),
                    }
                    writer.writerow(row_to_write)
        print("CSV successfully made")

if __name__ == "__main__":
    loader = DocumentLoader(environment="phi-test-accomplish")
    #loader.make_csv()
    valid_rows = loader.validate_as_csv(delimiter=",")
    loader.load(valid_rows)
