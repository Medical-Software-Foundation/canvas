import re, pytz, arrow, csv, json
from collections import defaultdict

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.template_migration.utils import validate_header, validate_required, validate_date, validate_enum, MappingMixin

from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    MappingMixin,
    FileWriterMixin
)
from data_migrations.template_migration.note import NoteMixin
from data_migrations.template_migration.commands import CommandMixin


class MedicationLoaderMixin(MappingMixin, NoteMixin, FileWriterMixin, CommandMixin):
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
                    "SIG",
                    "Medication Name",
                    "Original Code"
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Status": [validate_required, (validate_enum, {"possible_options": ['active', 'stopped']})]
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

    def load(self, validated_rows, note_kwargs={}):
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

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""
            try:
                # try mapping required Canvas identifiers
                patient_key = self.map_patient(patient)
                note_id = row.get("Note ID") or self.get_or_create_historical_data_input_note(patient_key, **note_kwargs)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            payload = {
                "resourceType": "MedicationStatement",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_id,
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

            # add the right coding depending on if it unstructured or FDB
            if row["RxNorm/FDB Code"] == 'unstructured':
                payload["medicationCodeableConcept"] =  {"coding": [
                    {
                        "system": "unstructured",
                        "code": "N/A",
                        "display": row['Medication Name']
                    }
                ]}
            else:
                payload["medicationReference"] = {
                    "reference": f'Medication/fdb-{row["RxNorm/FDB Code"]}',
                }

            #print(json.dumps(payload, indent=2))

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)

    def load_via_commands_api(self, validated_rows, note_kwargs={}):
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

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""

            if row["RxNorm/FDB Code"] == "unstructured":
                text = row["Medication Name"]
                code = row["Medication Name"]
                coding = [
                    {
                        "code": "",
                        "system": "UNSTRUCTURED",
                        "display": text
                    }
                ]
            elif not row['RxNorm/FDB Code']:
                coding = self.med_mapping[f"{row['Medication Name']}|{row.get('Original Code', '')}".lower()]
                code = next(item['code'] for item in coding if item["system"] == 'http://www.fdbhealth.com/')
                text = next(item['display'] for item in coding if item["system"] == 'http://www.fdbhealth.com/')
            else:
                code = row['RxNorm/FDB Code']
                text = row['Medication Name']

            try:
                patient_key = self.map_patient(patient)
            except Exception as e:
                self.ignore_row(row["ID"], str(e))
                continue

            note_id = row.get("Note ID") or self.get_or_create_historical_data_input_note(patient_key, **note_kwargs)

            payload = {
                "noteKey": note_id,
                "schemaKey": "medicationStatement",
                "values": {
                    "sig": row['SIG'],
                    "medication": {
                        "text": text,
                        "value": code,
                        "extra": {
                            "coding": coding
                        }
                    }
                }
            }

            try:
                canvas_id = self.create_command(payload)
                self.commit_command(canvas_id)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
