import arrow, csv

from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.allergy import AllergyLoaderMixin

class AllergyLoader(AllergyLoaderMixin):
    """
        Load Allergies from Elation to Canvas.

        Elation customer already gave us CSV in desired format, we will 
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
        self.data_type = 'allergies'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.allergy_map_file = "mappings/allergy_coding_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
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
        self.allergy_map = fetch_from_json(self.allergy_map_file)

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
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider",
            "Severity",
            'Original Name'
        }

        codes_to_map = set()

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)

                for row in reader:
                    customer_name = row['Name']
                    row['ID'] = f'{row["Patient Identifier"]}-{customer_name}'
                    
                    if found_mapping := self.allergy_map.get(f'{customer_name}|'.lower()):
                        for item in found_mapping:
                            if item['system'] == "http://www.fdbhealth.com/":
                                row['FDB Code'] = item["code"]
                                row['Name'] = item["display"]
                    else:
                        # codes_to_map.add(f'{customer_name}|')
                        row['FDB Code'] = "1-143" # Code for no allergy information available

                    free_text_note = row['Free Text Note']
                    if "Severity level: mild" in free_text_note:
                        row['Severity'] = 'Mild'
                        row['Free Text Note'] = free_text_note.replace("Severity level: mild", "")
                    elif "Severity level: moderate" in free_text_note:
                        row['Severity'] = 'Moderate'
                        row['Free Text Note'] = free_text_note.replace("Severity level: moderate", "")
                    elif "Severity level: severe" in free_text_note:
                        row['Severity'] = 'Severe'
                        row['Free Text Note'] = free_text_note.replace("Severity level: severe", "")
                    elif free_text_note.lower() in ('mild', 'severe', 'moderate'):
                        row['Severity'] = free_text_note.lower().capitalize()
                        row['Free Text Note'] = ""

                    row['Original Name'] = customer_name
                    writer.writerow(row)

            print("CSV successfully made")
            print(codes_to_map)

        

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = AllergyLoader(environment="phi-chronius-test")
    delimiter = ','

    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows)


# import csv
# with open("done_allergies.csv", 'r') as f:
#     reader = csv.DictReader(f, delimiter='|')
#     for row in reader:
#         name = row['id'].split('-')[-1]
#         print(name)

#         allergy = AllergyIntolerance.objects.get(externally_exposable_id=row['canvas_externally_exposable_id'])
#         print(f'allergy narrative = {allergy.narrative}')


#         notes = "Notes: "
#         reaction = ""

#         split = allergy.narrative.split('\n')
#         for item in split:
#             if item == name:
#                 pass
#             elif item.startswith('Notes:'):
#                 notes = item
#             else:
#                 reaction = item

#         new_notes = f"Name: {name}\nReaction: {reaction}\n{notes}"
#         print(f"New note to save = {new_notes}")

#         ct = ContentType.objects.get_for_model(allergy)
#         command = Relation.objects.get(object_id=allergy.id, content_type=ct).command
#         data = command.data
#         # print(f"command data = {data['narrative']}")


#         allergy.narrative = new_notes
#         allergy.save()
#         data['narrative'] = new_notes
#         command.save()

#         print()

