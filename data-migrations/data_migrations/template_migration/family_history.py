import csv
from collections import defaultdict

from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_enum,
    FileWriterMixin,
    MappingMixin,
)
from data_migrations.template_migration.commands import CommandMixin
from data_migrations.template_migration.note import NoteMixin
from data_migrations.utils import write_to_json


class FamilyHistoryMixin(MappingMixin, NoteMixin, FileWriterMixin, CommandMixin):

    self.relationship_code_to_display_map = {
        "72705000": "Mother",
        "66839005": "Father",
        "394859001": "Maternal grandmother",
        "27733009": "Sister",
        "70924004": "Brother",
        "394856008": "Paternal grandfather",
        "394857004": "Maternal grandfather",
        "394858009": "Paternal grandmother",
        "442051000124109": "Maternal aunt",
        "66089001": "Daughter",
        "65616008": "Son",
        "442041000124107": "Paternal uncle",
        "442031000124102": "Maternal uncle",
        "442061000124106": "Paternal aunt",
        "125679009": "Blood relative",
        "270002": "Female first cousin",
        "78652007": "Great grandmother",
        "394862003": "Great aunt",
        "11993008": "Male first cousin",
        "45929001": "Half-brother",
        "719769001": "Maternal great grandmother",
        "50261002": "Great grandfather",
        "34581001": "Niece",
        "83559000": "Nephew",
        "2272004": "Half-sister"
    }

    def validate(self, delimiter="|"):
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "patient",
                    "relative_coding",
                    "comment",
                    "icd_code",
                    "diagnosis_description",
                }
            )

            validations = {
                "id": [validate_required],
                "patient": [validate_required],
                "relative_coding": [(validate_enum, {"possible_options": self.relationship_code_to_display_map.keys()})]
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

            comment = row["comment"]
            snomed_code_and_description = self.icd10_to_snomed_mapping.get(row['icd_code'])
            if snomed_code_and_description:
                family_history_dict = {
                    "text": snomed_code_and_description[1],
                    "extra": {
                        "coding": [
                            {
                                "code": snomed_code_and_description[0],
                                "system": "http://snomed.info/sct",
                                "display": snomed_code_and_description[1],
                            }
                        ]
                    },
                    "value": snomed_code_and_description[0]
                }
            else:
                if not row["diagnosis_description"] and not row["icd_code"]:
                    self.ignore_row(row['id'], "Ignoring due to no diagnosis code or description.")
                    continue

                diagnosis_description = row["diagnosis_description"]
                if not diagnosis_description:
                    diagnosis_description = self.icd10_map[row["icd_code"].replace(".", "")]
                    if comment:
                        comment = f'{row["icd_code"]}\n{comment}'
                    else:
                        comment = f'{row["icd_code"]}'

                family_history_dict = {
                    "text": diagnosis_description,
                    "extra": {
                        "coding": [
                            {
                                "code": "",
                                "system": "UNSTRUCTURED",
                                "display": diagnosis_description,
                            }
                        ]
                    },
                    "value": diagnosis_description
                }

            payload = {
                "noteKey": historical_note,
                "state": "committed",
                "schemaKey": "familyHistory",
                "values": {
                    "note": comment,
                    "relative": {
                        "text": self.relationship_code_to_display_map[row["relative_coding"]],
                        "extra": {
                            "coding": {
                                "code": row["relative_coding"],
                                "system": "http://snomed.info/sct",
                                "display": self.relationship_code_to_display_map[row["relative_coding"]],
                            }
                        },
                        "value": row["relative_coding"]
                    },
                    "family_history": family_history_dict
                }
            }

            try:
                canvas_id = self.create_command(payload)
                self.commit_command(canvas_id)
                self.done_row(f"{row['id']}|{row['patient']}|{canvas_patient_key}|{canvas_id}")
                ids.add(row['id'])
            except BaseException as e:
                self.error_row(f"{row['id']}|{row['patient']}|{canvas_patient_key}", e)
