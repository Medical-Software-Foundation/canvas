import csv
from collections import defaultdict

from data_migrations.template_migration.commands import CommandMixin
from data_migrations.template_migration.note import NoteMixin
from data_migrations.template_migration.utils import (
    FileWriterMixin,
    MappingMixin,
    validate_header,
    validate_required,
    validate_date,
)
from data_migrations.utils import write_to_json


class ImmunizationMixin(CommandMixin, FileWriterMixin, MappingMixin, NoteMixin):
    def validate(self, delimiter=','):
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "Date Performed",
                    "Immunization Text",
                    "CVX Code",
                    "Comment",
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient Identifier": [validate_required],
                "Date Performed": [validate_required, validate_date],
                "Immunization Text": [validate_required],
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
        total_count = len(validated_rows)
        print(f'      Found {total_count} records')
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

            if row["CVX Code"]:
                coding_list = [
                    {
                        "code": row["CVX Code"],
                        "system": "http://hl7.org/fhir/sid/cvx",
                        "display": row["Immunization Text"]
                    }
                ]
            else:
                coding_list = [
                    {
                        "code": "",
                        "system": "UNSTRUCTURED",
                        "display": row["Immunization Text"]
                    }
                ]

            commands_sdk_payload = {
                "schemaKey": "immunizationStatement",
                "noteKey": note_id,
                "values": {
                    "date": {
                        "date": row["Date Performed"],
                        "input": row["Date Performed"],
                    },
                    "comments": row["Comment"],
                    "statement": {
                        "text": row["Immunization Text"],
                        "extra": {
                            "coding": coding_list
                        },
                        "value": row["Immunization Text"],
                        "annotations": [],
                        "description": ""
                    }
                }
            }

            try:
                command_uuid = self.create_command(commands_sdk_payload)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{command_uuid}")
                ids.add(row['ID'])
                self.commit_command(command_uuid)
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
