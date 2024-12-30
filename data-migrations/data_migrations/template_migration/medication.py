import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from utils import validate_header, validate_required, validate_date, validate_enum, MappingMixin

class MedicationLoaderMixin(MappingMixin):
    """
        Canvas has outlined a CSV template for ideal data migration that this Mixin will follow. 
        It will confirm the headers it expects as outlined in the template and validate each column.
        Trying to convert or confirm the formats are what we expect:

        Required Formats/Values (Case Insensitive):  
            Patient Identifier: Canvas key, unique identifier defined on the demographics page 
            Status: Active, Resolved
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
                    "Status",
                    "RxNorm/FDB Code",
                    "SIG"
                }  
            )

            validations = {
                "Patient Identifier": validate_required,
                "Status": validate_required,
                "RxNorm/FDB Code": validate_required,
                "Status": (validate_enum, {"possible_options": ['active', 'resolved']})
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
        print(f'      Found {len(validated_rows)} appointments')
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
            except BaseException as e:
                e = str(e).replace('\n', '')
                with open(self.errored_file, 'a') as errored:
                    print(f' {e}')
                    errored.write(f"{row['id']}|{row['patient']}|{patient_key}|{e}\n")
                    continue


            payload = {
                "resourceType": "MedicationStatement",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_key,
                    }
                ],
                "status": row['Status'],
                "subject": {
                    "reference": f"Patient/{patient_key}"
                },
                "dosage": ([
                    {
                        "text": row['SIG']
                    }
                ] if row['SIG'] else [])
            }

            # mapping_key = f"{row['rxnorm']}|{row['name']}".lower()
            # found_code = self.medication_map.get(mapping_key)
            # if found_code:
            #     if type(found_code) == str:
            #         found_code = eval(found_code)
            #     code = next(item['code'] for item in found_code if item["system"] == 'http://www.fdbhealth.com/')
            #     payload["medicationReference"] = {
            #         "reference": f"Medication/fdb-{code}",
            #     }
            # elif row['ndc'] and row['ndc'] != '0':
            #     payload["medicationCodeableConcept"] =  {"coding": [
            #         {
            #             "system": "http://hl7.org/fhir/sid/ndc",
            #             "code": row['ndc'],
            #             "display": row['name']
            #         }
            #     ]}
            # else:
            #     payload["medicationCodeableConcept"] =  {"coding": [
            #         {
            #             "system": "unstructured",
            #             "code": "N/A",
            #             "display": row['name'] or row['signature_note'] or row['notes']
            #         }
            #     ]}

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