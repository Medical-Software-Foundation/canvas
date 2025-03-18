import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import validate_header, validate_required, validate_datetime, MappingMixin, FileWriterMixin
from data_migrations.template_migration.note import NoteMixin


class QuestionnaireResponseLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow.
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect
    """

    def validate(self, delimiter='|'):
        """ 
            Loop throw the CSV file to validate each row has the correct columns and values
            Append validated rows to a list to use to load. 
            Export errors to a file/console
            
        """
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames, 
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "DOS",
                    "Provider",
                    "Location",
                    "Note Type Name",
                    "Note ID",
                    "Note Title",
                    "Questionnaire ID",
                    "Questions",
                }  
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "DOS": [validate_required, validate_datetime],
                "Questionnaire ID": [validate_required],
            }
            
            for row in reader:
                error = False
                key = f"{row['ID']} {row['Patient Identifier']}"
                
                for field, validator_funcs in validations.items():
                    for validator_func in validator_funcs:
                        kwargs = {}
                        if isinstance(validator_func, tuple): 
                            validator_func, kwargs = validator_func
                        
                        valid, value = validator_func(row[field].strip(), field, **kwargs)
                        if valid:
                            row[field] = value
                        else:
                            errors[key].append(value)
                            error = True

                if not error:
                    validated_rows.append(row)

        if errors:
            print(f"Some rows contained errors, please see {self.validation_error_file}.")
            write_to_json(self.validation_error_file, errors)
        else:
            print('All rows have passed validation!')

        return validated_rows

    def load(self, validated_rows):
        """
            Takes the validated rows from self.validate() and
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records
            If any  error, the error message will output to the errored file
        """
        self.patient_map = fetch_from_json(self.patient_map_file) 

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):

            print(f'Ingesting ({i+1}/{total_count})')
 
            if row['ID'] in ids or row['ID'] in self.done_records or row['ID'] in self.ignore_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""

            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                practitioner_key = self.map_provider(row.get('Provider'))
                location = self.map_location(row.get('Location'))
                if note_id := row.get("Note ID"):
                    self.perform_note_state_change(note_id, 'ULK')
                else:
                    note_id = self.create_note(patient_key, **{
                        "note_type_name": row['Note Type Name'],
                        "provider_key": practitioner_key,
                        "encounter_start_time": row['DOS'],
                        "practice_location_key": row['Location'],
                        "note_title": row.get("Note Title")
                    })
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            questions = row['Questions']
            if isinstance(questions, str):
                questions = json.loads(questions)


            payload = {
                "resourceType": "QuestionnaireResponse",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_id
                    }
                ],
                "questionnaire": f"Questionnaire/{row['Questionnaire ID']}",
                "status": "in-progress",
                "subject": {
                    "reference": f"Patient/{patient_key}",
                    "type": "Patient"
                },
                "authored": row['DOS'],
                "author": {
                    "reference": f"Practitioner/{practitioner_key}",
                    "type": "Practitioner"
                },
                "item": [
                    {
                        "linkId": question_id,
                        "answer": answer
                    }
                for question_id, answer in questions.items()] 
            }
            #print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.perform_note_state_change(note_id)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
                continue
