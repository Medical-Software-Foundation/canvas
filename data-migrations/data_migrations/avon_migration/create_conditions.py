import csv, os

from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows

from utils import AvonHelper

class ConditionLoader(ConditionLoaderMixin):
    """
        Load Conditions from Avon to Canvas.

        First makes the Avon List API call and converts the results into a CSV
        then loops through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

        It also produces multiple files:
        - The done_file keeps track of the Avon unique identifier to the canvas
          appointment id and patient key. This helps ensure no duplicate data is transfered and
          helps keep an audit of what was loaded.
        - The error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any data that may need manual fixing and replaying
        - The ignore file keeps track of any records that were skipped over
          during the ingest process potentially due to a patient not being
          in canvas, doctor not being in canvas, etc
        - The validation_error_file keeps track of all the Avon records that failed the validation of
          the Canvas Data Migration Template and why they failed
    """


    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = "PHI/conditions.json"
        self.csv_file = 'PHI/conditions.csv'
        self.ignore_file = 'results/ignored_conditions.csv'
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.validation_error_file = 'results/errored_condition_validation.json'
        self.error_file = 'results/errored_conditions.csv'
        self.done_file = 'results/done_conditions.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.avon_helper = AvonHelper(environment)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.icd10_map_file = "../template_migration/mappings/icd10_map.json"
        self.icd10_map = fetch_from_json(self.icd10_map_file)

        # default needed for mapping
        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter='|'):
        """
            Fetch the Condition Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/conditions", self.json_file, param_string='')

        headers = {
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "ICD-10 Code",
            "Onset Date",
            "Resolved Date",
            "Recorded Provider",
            "Free text notes",
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                if row["name"] is None or not row['name'].strip():
                    self.ignore_row(row['id'], "No condition name found to map")
                    continue

                name_map = {
                    "ADHD": "F909",
                    "Attention deficit disorder": "F909",
                    "B12 deificiency": "D518",
                    "Bloating": "R140",
                    "BRCA 1": "Z1501",
                    "chronic low back Pain": "M545",
                    "DCIS": "D0510",
                    "DVT": "I82409",
                    "dyslipdemia": "E785",
                    "Dyslipidemia": "E785",
                    "eczema": "L209",
                    "Endometrial Cancer": "C541",
                    "Endometrosis": "N809",
                    "eosionphilic esophagitis": "K200",
                    "Factor 2 Mutation": "D6852",
                    "Factor V Leiden": "D682",
                    "fibroids": "D250",
                    "GERD": "K219",
                    "Hashimotos": "E063",
                    "Hashimoto's": "E063",
                    "hot flash": "N951",
                    "HTN": "I10",
                    "Hx of DVT and PE s/p COVID vaccine": "Z86718",
                    "Hypertrophic Cardiomyopathy": "I422",
                    "Hypothyrodism": "E039",
                    "Hypovitaminosis": "E569",
                    "Kidney stones": "N200",
                    "Leukopenia": "D72819",
                    "Low Ferritin": "E611",
                    "Low ferritin": "E611",
                    "low libdo": "R6882",
                    "May-Thurner Syndrome": "I871",
                    "Menopause": "N951",
                    "Migraines": "G43909",
                    "Migrane": "G43909",
                    "Migranes": "G43909",
                    "migranes": "G43909",
                    "Migranes with aura": "G43109",
                    "MTHFR": "E7212",
                    "MTHFR gene": "E7212",
                    "MTHRF-hetrozygeous": "E7212",
                    "Osteopenia": "M8580",
                    "OSTEOPENIA": "M8580",
                    "osteopenia": "M8580",
                    "Osteopenia": "M8580",
                    "PCOS": "E282",
                    "Pericarditis/Pericardial Effusion": "I319",
                    "Perimenopause": "N959",
                    "persistent perceptual postural dizziness PPPD": "G90A",
                    "Post-menopause": "N950",
                    "Post-Menopause": "N950",
                    "Post-Menopause,": "N950",
                    "Postmenopause": "N950",
                    "Pre-diabetic": "R7303",
                    "Prediabetes,": "R7303",
                    "Prediabetes": "R7303",
                    "Premature ventricular contractions": "I493",
                    "Provoked DVT": "I82409",
                    "PTSD": "F4310",
                    "Right Venous Thoracic Outlet Syndrome": "G540",
                    "Seasonal Allergies": "J302",
                    "Seasonal allergies": "J302",
                    "Sjorgen's Syndrome": "M3500",
                    "Stage 2 Right Mucinous Carcinoma.": "C561",
                    "Subclinical Hypothyroidism": "E02",
                    "submassive saddle pulmonary embolism": "I2602",
                    "Thymic gland carcinoma": "C37",
                    "Ventricular Fibrillation Arrest": "I4901",
                    "VTE": "I8290",
                    "weight gan": "R635",
                }

                writer.writerow({
                    "ID": row["id"],
                    "Patient Identifier": row["patient"],
                    "Clinical Status": "active" if row["active"] else "resolved",
                    "ICD-10 Code": name_map.get(row["name"].strip()) or row["name"],
                    "Onset Date": row["onset_date"] or "",
                    "Resolved Date": row["end_date"] if row["end_date"] and not row["active"] else "",
                    "Recorded Provider": row["created_by"] if row["created_by"] != "user_null" else "5eede137ecfe4124b8b773040e33be14",
                    "Free text notes": row["comment"].replace("\n", "\\n") if row["comment"] else "",
                })

            print("CSV successfully made")


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = ConditionLoader(environment='phi-collaborative-test')
    delimiter = '|'

    # Make the Avon API call to their List Appointments endpoint and convert the JSON return
    # to the template CSV loader
    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows)
