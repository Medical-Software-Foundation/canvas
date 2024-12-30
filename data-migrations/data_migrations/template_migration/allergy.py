import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from utils import validate_header, validate_required, validate_date, validate_enum, MappingMixin

class AllergyLoaderMixin(MappingMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow. 
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):  
            Patient Identifier: Canvas key, unique identifier defined on the demographics page
            Clinical Status: Active, Resolved
            Type: Allergy, Intolerance 
            Onset Date: MM/DD/YYYY or YYYY-MM-DD  
            Recorded Provider: Staff Canvas key.  If omitted, defaults to Canvas Bot
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
                    "Clinical Status",
                    "Type",
                    "FDB Code",
                    "Onset Date",
                    "Free Text Note",
                    "Reaction",
                    "Recorded Provider"

                }  
            )

            validations = {
                "Patient Identifier": validate_required,
                "Clinical Status": validate_required,
                "Type": validate_required,
                "FDB Code": validate_required,
                "Onset Date": validate_date,
                "Clinical Status": (validate_enum, {"possible_options": ['active', 'inactive']})
            }
            
            for row in reader:
                error = False
                key = f"{row['ID']} {row['Patient Identifier']}"
                
                for field, validator_func in validations.items():
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

    def load(self, validated_rows, system_unique_identifier):
        """
            Takes the validated rows from self.validate() and 
            loops through to send them off the FHIR Create

            Outputs to CSV to keep track of records 
            If any  error, the error message will output to the errored file
        """

        self.patient_map = fetch_from_json(self.patient_map_file) 

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['id'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                practitioner_key = self.map_provider(row['Recorded Provider'])
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_file, 'a') as errored:
                    print(f' {e}')
                    errored.write(f"{row['id']}|{row['patient']}|{patient_key}|{e}\n")
                    continue


            payload = {
                "resourceType": "AllergyIntolerance",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_key,
                    }
                ],
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": row['Clinical Status']
                        }
                    ],
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/rowintolerance-verification",
                            "code": "confirmed",
                            "display": "Confirmed"
                        }
                    ],
                    "text": "Confirmed"
                },
                "type": row['Type'],
                "code": {
                    "coding": [
                        {
                            "system": "http://www.fdbhealth.com/",
                            "code": row['FDB Code']
                        }
                    ]
                },
                "patient": {
                    "reference": f"Patient/{patient_key}"
                },
                "note": (
                    ([{"text": row['reaction']}] if row['reaction'] else []) +
                    ([{"text": f"Notes: {row['Free Text Note']}"}] if row['Free Text Note'] else [])
                )
            }

            if onset := row['Onset Date']:
                payload['onsetDateTime'] = onset
            if practitioner_key:
                payload['recorder'] = {
                    "reference": f"Practitioner/{practitioner_key}"
                }


            # print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                with open(self.done_file, 'a') as done:
                    print(' Complete')
                    done.write(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}\n")
            except BaseException as e:            
                e = str(e).replace('\n', '')
                with open(self.errored_file, 'a') as errored:
                    print(' Errored')
                    errored.write(f"{row['ID']}|{patient}|{patient_key}|{e}\n")
                continue 