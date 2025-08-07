import csv, json
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows, write_to_json
from data_migrations.template_migration.lab_report import LabReportDocumentOnlyMixin

class DocumentLoader(LabReportDocumentOnlyMixin):
    """
        Takes the CSV customer gave us and converts the results into our templated CSV
        then loops through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

        It also produces multiple files:
        - The done_file keeps track of the unique identifier to the canvas 
          appointment id and patient key. This helps ensure no duplicate data is transfered and 
          helps keep an audit of what was loaded.
        - The error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any data that may need manual fixing and replaying
        - The ignore file keeps track of any records that were skipped over
          during the ingest process potentially due to a patient not being 
          in canvas, doctor not being in canvas, etc
        - The validation_error_file keeps track of all the records that failed the validation of 
          the Canvas Data Migration Template and why they failed
    """


    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'lab_reports'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'
        #self.documents_files_dir = "PHI/chroniusfiles/"
        # self.documents_files_dir = "PHI/lab report documents 7-10/"
        # self.documents_files_dir = "PHI/other documents 7-10/"
        # self.documents_files_dir = "PHI/missing documents files/"
        self.documents_files_dir = "PHI/all documents 7-17/"


        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|', use_identifier_to_find_file=False):
        """
            Fetch the Records from customer given file
            and convert into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        headers = {
            "ID",
            "Patient Identifier",
            "Lab Date",
            "Document",
            "Lab Test Name",
            "Lab LOINC Code"
        }


        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    document_name = row['Document']
                    if use_identifier_to_find_file:
                        document_name = f'{row["ID"]}.pdf'

                    writer.writerow({
                        "ID": row['ID'],
                        "Patient Identifier": row['Patient Identifier'],
                        "Lab Date": row['Lab Date'] or "2025-07-17",
                        "Document": json.dumps([document_name]),
                        "Lab Test Name": row['Document'].split('.pdf')[0],
                        "Lab LOINC Code": "11502-2"
                    })


                print("CSV successfully made")

if __name__ == '__main__':
    loader = DocumentLoader(environment="chronius")
    delimiter = ','
    #loader.make_csv(delimiter, use_identifier_to_find_file=True)
    valid_rows = loader.validate(delimiter)
    loader.load(valid_rows)


""" 
Will need to manually mark these as review not required since that can't be controlled via API
An engineer that can ssh into the instance will need to run this
"""

# count = 0
# labs = LabReport.objects.filter(review_mode='RR')
# print(labs.count())
# for l in labs:
#     # if l.name == 'Lab':
#     count += 1
#     print(count)
#     l.review_mode = 'RN'
#     l.save()
# print(count)