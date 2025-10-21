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
         "270002": 'Female first cousin',
         "2272004": 'Half-sister',
         "2368000": 'Great great grandmother',
         "11434005": 'Male second cousin',
         "11993008": 'Male first cousin',
         "21506002": 'Female second cousin',
         "27733009": 'Sister',
         "29644004": 'Fraternal twin sister',
         "30578000": 'Stepfather',
         "34581001": 'Niece',
         "45929001": 'Half-brother',
         "50058005": 'Identical twin sister',
         "50261002": 'Great grandfather',
         "65616008": 'Son',
         "66089001": 'Daughter',
         "66839005": 'Father',
         "70924004": 'Brother',
         "72705000": 'Mother',
         "78194006": 'Identical twin brother',
         "78652007": 'Great grandmother',
         "80386000": 'Great great grandfather',
         "81467001": 'Fraternal twin brother',
         "83559000": 'Nephew',
         "85683001": 'Adopted',
         "125679009": 'Blood relative',
         "394856008": 'Paternal grandfather',
         "394857004": 'Maternal grandfather',
         "394858009": 'Paternal grandmother',
         "394859001": 'Maternal grandmother',
         "394861005": 'Great uncle',
         "394862003": 'Great aunt',
         "719768009": 'Paternal great grandmother',
         "719769001": 'Maternal great grandmother',
         "719770000": 'Paternal great grandfather',
         "719771001": 'Maternal great grandfather',
         "442031000124102": 'Maternal uncle',
         "442041000124107": 'Paternal uncle',
         "442051000124109": 'Maternal aunt',
         "442061000124106": 'Paternal aunt',
    }

    def validate(self, delimiter="|"):
        validated_rows = []
        errors = defaultdict(list)
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "ID",
                    "Patient Identifier",
                    "Relative Coding",
                    "Comment",
                    "ICD10/SNOMED Code",
                    "Diagnosis Name",
                }
            )

            validations = {
                "ID": [validate_required],
                "Patient": [validate_required],
                "Relative Coding": [(validate_enum, {"possible_options": self.relationship_code_to_display_map.keys()})]
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

        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()

        for i, row in enumerate(validated_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['ID'] in ids or row['ID'] in self.done_records:
                print(' Already did record')
                continue

            try:
                canvas_patient_key = self.map_patient(row["Patient Identifier"])
            except Exception as e:
                self.ignore_row(row["ID"], str(e))
                continue

            historical_note = self.get_or_create_historical_data_input_note(canvas_patient_key)

            comment = row["Comment"]
            snomed_code_and_description = self.icd10_to_snomed_mapping.get(row['ICD10/SNOMED Code'])
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
                if not row["Diagnosis Name"] and not row["ICD10/SNOMED Code"]:
                    self.ignore_row(row['id'], "Ignoring due to no diagnosis code or description.")
                    continue

                diagnosis_description = row["Diagnosis Name"]
                if not diagnosis_description:
                    diagnosis_description = self.icd10_map[row["ICD10/SNOMED Code"].replace(".", "")]
                    if comment:
                        comment = f'{row["ICD10/SNOMED Code"]}\n{comment}'
                    else:
                        comment = f'{row["ICD10/SNOMED Code"]}'

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
                        "text": self.relationship_code_to_display_map[row["Relative Coding"]],
                        "extra": {
                            "coding": {
                                "code": row["Relative Coding"],
                                "system": "http://snomed.info/sct",
                                "display": self.relationship_code_to_display_map[row["Relative Coding"]],
                            }
                        },
                        "value": row["Relative Coding"]
                    },
                    "family_history": family_history_dict
                }
            }

            try:
                canvas_id = self.create_command(payload)
                self.commit_command(canvas_id)
                self.done_row(f"{row['ID']}|{row['Patient Identifier']}|{canvas_patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{row['Patient Identifier']}|{canvas_patient_key}", e)
