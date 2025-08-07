import csv, json
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows, write_to_json
from data_migrations.template_migration.document_reference import DocumentReferenceMixin

class DocumentLoader(DocumentReferenceMixin):
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
        self.data_type = 'documents'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'
        # self.documents_files_dir = "PHI/chroniusfiles/"
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
            "Type",
            "Clinical Date",
            "Category",
            "Document",
            "Description",
            "Provider",
            "Comment",
        }

        doc_map = {
            "Specialist Consult Report": ("34109-9", "uncategorizedclinicaldocument"),
            "Imaging Report": ("34109-9", "uncategorizedclinicaldocument"),
            "Disability Form": ("51851-4", "patientadministrativedocument"),
            "External Medical Records": ("11503-0", "uncategorizedclinicaldocument"),
            "Uncategorized Clinical Document": ("34109-9", "uncategorizedclinicaldocument"),
            "Rehabilitation Report": ("34823-5", "uncategorizedclinicaldocument"),
            "Physical Exams": ("51848-0", "uncategorizedclinicaldocument"),
            "In-Office Testing": ("34109-9", "uncategorizedclinicaldocument"),
            "Hospital Discharge Summary": ("34105-7", "uncategorizedclinicaldocument"),
            "Uncategorized Administrative Document": ("51851-4", "patientadministrativedocument"),
            "Release of Information Request": ("101904-1", "patientadministrativedocument"),
            "Insurance Card": ("64290-0", "patientadministrativedocument"),
            "Patient Clinical Intake Form": ("64285-0", "uncategorizedclinicaldocument"),
            "Operative Report": ("11504-8", "uncategorizedclinicaldocument"),
            "Emergency Department Report": ("96335-5", "uncategorizedclinicaldocument"),
            "Chronius Care Plan": ("34109-9", "uncategorizedclinicaldocument"),
            "Hospital History & Physical": ("47039-3", "uncategorizedclinicaldocument"),
            "Care Management": ("91983-7", "uncategorizedclinicaldocument"),
            "Patient Agreement": ("80570-5", "patientadministrativedocument"),
            "Patient Consent": ("51851-4", "patientadministrativedocument"),
            "Insurer Prior Authorization": ("52034-6", "patientadministrativedocument"),
            "Handicap Parking Permit": ("51851-4", "patientadministrativedocument"),
            'Prescription Refill Request': ("57833-6", "uncategorizedclinicaldocument"),
            'Patient Assistance': ("51851-4", "patientadministrativedocument"),
            "Worker's Compensation Documents": ("52070-0", "patientadministrativedocument"),
            'Home Care Report': ("75503-3", "uncategorizedclinicaldocument"),
            'Medicaid Documents': ("51851-4", "patientadministrativedocument"),
            'Patient Administrative Intake Form': ("51851-4", "patientadministrativedocument"),
            'Prescription Card': ("51851-4", "patientadministrativedocument"),

        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)
                for row in reader:
                    if not row['Type']:
                        _type, category = ("34109-9", "uncategorizedclinicaldocument")
                    else:
                        _type, category = doc_map[row['Type']]
                    document_name = row['Document']
                    if use_identifier_to_find_file:
                        document_name = f'{row["ID"]}.pdf'

                    writer.writerow({
                        "ID": row['ID'],
                        "Patient Identifier": row['Patient Identifier'],
                        "Type": _type,
                        "Clinical Date": row['Clinical Date'].replace("Unable to determine", '') or "2025-07-17",
                        "Category": category,
                        "Document": json.dumps([document_name]),
                        "Description": row['Document'].split('.pdf')[0],
                        "Provider": "",
                        "Comment": f"{row['Type']} - {row['Description']}"
                    })


                print("CSV successfully made")

if __name__ == '__main__':
    loader = DocumentLoader(environment="chronius")
    delimiter = ','
    #loader.make_csv(delimiter, use_identifier_to_find_file=True)
    valid_rows = loader.validate_as_csv(delimiter=",")
    loader.load(valid_rows)
