import csv
from collections import defaultdict

from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_date,
    FileWriterMixin,
    MappingMixin,
)
from data_migrations.template_migration.commands import CommandMixin
from data_migrations.template_migration.note import NoteMixin
from data_migrations.utils import write_to_json


class SurgicalHistoryMixin(MappingMixin, NoteMixin, FileWriterMixin, CommandMixin):

    def validate(self, delimiter="|"):
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "id",
                    "patient",
                    "comment",
                    "date_performed",
                    "snomed_code",
                    "snomed_text",
                }
            )

            validations = {
                "id": [validate_required],
                "patient": [validate_required],
                "snomed_code": [validate_required],
                "snomed_text": [validate_required],
                "date_performed": [validate_date],
            }

            for row in reader:
                error = False
                key = f"{row['id']} {row['patient']}"

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

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()

        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['id'] in ids or row['id'] in self.done_records:
                print(' Already did record')
                continue

            try:
                canvas_patient_key = self.map_patient(row["patient"])
            except Exception as e:
                self.ignore_row(row["id"], str(e))
                continue

            historical_note = self.get_or_create_historical_data_input_note(canvas_patient_key)
            approximate_date = row["date_performed"]
            if approximate_date:
                approximate_date = {
                    "date": row["date_performed"],
                    "input": row["date_performed"]
                }
            else:
                approximate_date = None

            payload = {
                "noteKey": historical_note,
                "state": "committed",
                "schemaKey": "surgicalHistory",
                "values": {
                    "comment": row["comment"],
                    "approximate_date": approximate_date,
                    "past_surgical_history":
                    {
                        "text": row["snomed_text"],
                        "extra":
                        {
                            "coding":
                            [
                                {
                                    "code": int(row["snomed_code"]),
                                    "system": "http://snomed.info/sct",
                                    "display": row["snomed_text"]
                                }
                            ]
                        },
                        "value": int(row["snomed_code"]),
                        "disabled": False,
                        "annotations": None,
                        "description": None
                    }
                }
            }

            try:
                canvas_id = self.create_command(payload)
                self.commit_command(canvas_id)
                self.done_row(f"{row['id']}|{row['patient']}|{canvas_patient_key}|{canvas_id}")
                ids.add(row['id'])
            except BaseException as e:
                self.error_row(f"{row['id']}|{row['patient']}|{canvas_patient_key}", e)
