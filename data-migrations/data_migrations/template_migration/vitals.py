import csv
from collections import defaultdict

from data_migrations.template_migration.commands import CommandMixin
from data_migrations.template_migration.note import NoteMixin
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_datetime,
    FileWriterMixin,
    MappingMixin
)
from data_migrations.utils import write_to_json


class VitalsMixin(NoteMixin, CommandMixin, MappingMixin, FileWriterMixin):

    def convert_weight_to_lbs_ounces(self, weight_val):
        if "." in weight_val:
            pounds, pounds_decimal = weight_val.split(".")
            return pounds, str(int(float(pounds_decimal) * 16))
        return weight_val, None


    def validate(self, delimiter=","):
        validated_rows = []
        errors = defaultdict(list)

        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "id",
                    "patient",
                    "height",
                    "weight_lbs",
                    "body_temperature",
                    "blood_pressure_systole",
                    "blood_pressure_diastole",
                    "pulse",
                    "respiration_rate",
                    "oxygen_saturation",
                    "created_by",
                    "created_at",
                    "comment",
                }
            )

            validations = {
                "id": [validate_required],
                "patient": [validate_required],
                'created_at': [validate_required, validate_datetime]
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

    def load(self, valid_rows):
        total_count = len(valid_rows)
        print(f'      Found {len(valid_rows)} records')
        ids = set()
        for i, row in enumerate(valid_rows):
            print(f'Ingesting ({i+1}/{total_count})')

            if row['id'] in ids or row['id'] in self.done_records:
                print(' Already did record')
                continue

            patient_key = ""
            try:
                patient_key = self.map_patient(row["patient"])
            except BaseException as e:
                self.ignore_row(row['id'], e)
                continue

            provider_key = self.doctor_map.get(row["created_by"], "5eede137ecfe4124b8b773040e33be14") # fallback to canvas bot

            vitals_values = {}

            if height := row["height"]:
                vitals_values["height"] = str(height)

            if weight := row["weight_lbs"]:
                lbs, ounces = self.convert_weight_to_lbs_ounces(weight)
                vitals_values["weight_lbs"] = lbs
                vitals_values["weight_oz"] = ounces

            if body_temperature := row["body_temperature"]:
                vitals_values["body_temperature"] = str(body_temperature)

            # some values in the commands payload are integers; convert those here
            for val in ["pulse", "respiration_rate", "oxygen_saturation", "blood_pressure_systole", "blood_pressure_diastole"]:
                if row[val]:
                    try:
                        int_value = int(row[val])
                        vitals_values[val] = int_value
                    except ValueError as e:
                        print(f"Invalid integer value for {val} - {row[val]}")

            if comment := row["comment"]:
                vitals_values["note"] = comment

            # ignore the record if there are no vitals values present (some of them may be all null)
            if not vitals_values:
                self.ignore_row(row['id'], "Ignoring due to vital sign data all null")
                continue

            try:
                vitals_import_note = self.create_note(
                    note_type_name="Vitals Data Import",
                    canvas_patient_key=patient_key,
                    provider_key=provider_key,
                    encounter_start_time=row["created_at"],
                    practice_location_key=self.default_location
                )
            except Exception as e:
                self.error_row(f"{row['id']}|{row['patient']}|{patient_key}", e)
                continue

            vitals_payload = {
                "noteKey": vitals_import_note,
                "schemaKey": "vitals",
                "values": vitals_values
            }

            try:
                canvas_id = self.create_command(vitals_payload)
            except BaseException as e:
                self.error_row(f"{row['id']}|{row['patient']}|{patient_key}", e)
                continue

            self.done_row(f"{row['id']}|{row['patient']}|{patient_key}|{canvas_id}")
            ids.add(row['id'])

            try:
                self.commit_command(canvas_id)
            except BaseException as e:
                self.error_row(f"{row['id']}|{row['patient']}|{patient_key}", e)
                # still creates note, just unable to lock or commit command
                continue

            # now lock the Vitals Import note
            try:
                self.perform_note_state_change(vitals_import_note, state='LKD')
            except Exception as e:
                self.error_row(f"{row['id']}|{row['patient']}|{patient_key}", e)
