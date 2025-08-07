import csv, os

from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows

class ConditionLoader(ConditionLoaderMixin):
    """
        Load Conditions to Canvas.

        Customer already gave us CSV in desired format, we will 
        then loop through the CSV to validate the columns according to Canvas Data Migration Template
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
        self.data_type = 'conditions'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map = fetch_from_json(self.note_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        self.condition_mapping = fetch_from_json("mappings/condition_coding_map.json")

        self.icd10_map_file = "../template_migration/mappings/icd10_map.json"
        self.icd10_map = fetch_from_json(self.icd10_map_file)

        # default needed for mapping
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Chronius Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter=','):
        """
            Fetch the Condition Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        headers = {
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "ICD-10 Code",
            "Onset Date",
            "Resolved Date",
            "Recorded Provider",
            "Free text notes",
            "Name"
        }

        icd_map = {
            "Allergic Rhinitis": "J30.9",
            "Allergies": "T7840XS",
            "Angioedema": "T783XXS",
            "Anxiety with Depression": "F41.8",
            "Anxiety": "F41.9",
            "Asthma": "J45.909",
            "Attention-Deficit Disorder": "F90.9",
            "Bone and joint pain": "M25.50",
            "Breast Cysts": "N60.09",
            "Carotid artery sclerosis": "I65.29",
            "Carpal Tunnel Syndrome": "G56.00",
            "Carpal tunnel syndrome": "G56.00",
            "Cervical Disc Bulge": "M50.220",
            "Cervical Disc Herniation with Radiculopathy": "M50.10",
            "Clostridium difficile": "A04.72",
            "Complex Regional Pain Syndrome": "G90.50",
            "Dermatomyositis": "M33.90",
            "Diverticulosis": "K57.90",
            "Dry eyes": "H04.129",
            "Dysautonomia/Autonomic Dysfunction": "G90.9",
            "Endometriosis": "N809",
            "Environmental Allergy": "T7840XS",
            "Episcleritis": "H15.109",
            "Epstein-Barr Virus": "B27.00",
            "Esophagitis": "K200",
            "Food Allergy": "Z91018",
            "Gastroesophageal reflux disease": "K219",
            "Grand mal seizure": "G40.409",
            "Gustatory Rhinitis": "J30.89",
            "Hand Pain": "M79.643",
            "Hemiplegic migraines": "G43.409",
            "Hemoptysis": "R04.2",
            "Hip Pain": "M25.559",
            "Idiopathic Hypersomnia": "G47.10",
            "Iliotibial Band Syndrome": "M76.30",
            "Impacted teeth": "K011",
            "Iron deficiency anemia": "D50.9",
            "Iron Deficiency Anemia": "D50.9",
            "Jaw Osteoarthritis": "M26.629",
            "Lower Back/Hip Pain": "M54.5",
            "Lumbar spondylosis": "M47.896",
            "Macular degeneration": "H35.3190",
            "Mast Cell Activation Syndrome": "D89.40",
            "Mast Cell Activation Syndrome": "D89.40",
            "Medication intolerances": "Z889",
            "Methylenetetrahydrofolate reductase deficiency": "E72.12",
            "Migraines": "G43.909",
            "Mixed anxiety and depressive disorder": "F41.8",
            "Neck Pain": "M54.2",
            "Obsessive-Compulsive Disorder": "F42.9",
            "Ovarian Cysts": "N83.209",
            "Perimenopause": "N959",
            "Pes Planus": "M21.40",
            "Post-Traumatic Stress Disorder": "F43.10",
            "Psoriatic Arthritis": "L40.52",
            "Raynaud's Phenomenon": "I73.00",
            "Recurrent Urinary Tract Infection": "N39.0",
            "Regional Upper Extremity Complex Regional Pain Syndrome": "G90.519",
            "Reynauds": "I73.00",
            "Scoliosis": "M419",
            "Severe mono": "B27.99",
            "Sinus Polyps": "J33.9",
            "Small Intestinal Bacterial Overgrowth": "K63.8219",
            "Soft tissue swelling": "R229",
            "Spinal Stenosis": "M48.00",
            "Temporomandibular Joint Disorder": "M26609",
            "Temporomandibular joint disorder": "M26609",
            "Temporomandibular Joint Dysfunction": "M26609",
            "Temporomandibular Joint": "M26609",
            "Temporomandibular Joints": "M26609",
            "Tinnitus": "H93.19",
            "Umbilical hernia": "K429",
            "Vertigo": "R42",
            "Vit B12 deficiency": "D51.9",
            "Vitreous detachment": "H43.819",
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)

                for row in reader:
                    row['ID'] = f'{row["Patient Identifier"]}-{row["ICD-10 Code"]}-{row["Onset Date"]}'

                    input_name = row['Name']

                    if input_name in ('Medical Neglect', 'Post-surgical recovery'):
                        self.ignore_row(row['ID'], f"Ignoring condition {input_name}")
                        continue

                    # customer wanted the notes to have the original name
                    # if row['Free text notes']:
                    #     row['Free text notes'] = f"Name: {input_name}\n{row['Free text notes']}"
                    # else:
                    #     row['Free text notes'] = f"Name: {input_name}"

                    # customer tried to put the name in the notes for later drops, but want to keep same format
                    if ":" in row['Free text notes']:
                        split = row['Free text notes'].split(':')
                        row['Free text notes'] = f'Name: {split[0]}\n{":".join(split[1:])}'
                    else:
                        row['Free text notes'] = f"Name: {row['Free text notes']}"

                    row['ICD-10 Code'] = row['ICD-10 Code'].replace(' ', '').replace('.', '')

                    if mapping := self.condition_mapping.get(f"{input_name}|{row['ICD-10 Code']}"):
                        row['ICD-10 Code'] = mapping['code']
                    else:
                        row['ICD-10 Code'] = icd_map.get(input_name) or row['ICD-10 Code']

                    writer.writerow(row)

            print("CSV successfully made")


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = ConditionLoader(environment='phi-chronius-test')
    delimiter = ','

    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows)


# from django.contrib.contenttypes.models import ContentType

# qs = Condition.objects.filter(note__note_type_version__code='chronius_data_migration').exclude(notes="")
# for c in qs:
#     a = c.assessments.order_by('pk').first()
#     if not a:
#         print(f'Resolved condition skipping {c.id}')
#         continue
#     if c.notes != a.background:
#         print(f'{c.id} DOES NOT MATCH')
#         a.background = c.notes
#         a.save()

#         ct = ContentType.objects.get_for_model(c)
#         command = Relation.objects.get(object_id=c.id, content_type=ct).command
#         data = command.data
#         data['background'] = c.notes
#         command.data = data
#         command.save()


