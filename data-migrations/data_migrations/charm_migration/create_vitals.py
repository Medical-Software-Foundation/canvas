from decimal import Decimal
from collections import defaultdict
import arrow, csv, json

from data_migrations.template_migration.vitals import VitalsMixin
from data_migrations.utils import (
    fetch_from_json,
    write_to_json,
    fetch_complete_csv_rows,
    fetch_from_csv,
    load_fhir_settings
)
from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.utils import (
    validate_header,
    validate_required,
    validate_datetime,
)


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


class VitalsLoader(VitalsMixin):
    def __init__(self, environment) -> None:
        self.json_file = "PHI/vitals.json"
        self.csv_file = "PHI/vitals.csv"
        self.environment = environment
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)

        self.done_file = 'results/done_vitals.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_vitals.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_vitals.csv'
        self.fumage_helper = load_fhir_settings(environment)

        self.validation_error_file = "results/PHI/errored_vitals_validation.json"
        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.default_note_type_name = "Charm Historical Note"

        super().__init__()

    def make_json(self):
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]

        charm_patient_api = CharmPatientAPI(environment=self.environment)
        vitals = charm_patient_api.fetch_vitals(patient_ids=patient_ids)
        write_to_json(self.json_file, vitals)

    def convert_height_feet_and_inches_to_inches(self, feet, inches):
        # all of the values have either:
        # 1) A decimal (.x) in feet and no inches
        # 2) An integer (.0 in feet) and inches
        # 3) No feet and a decimal in inches

        return_val = None
        if feet == "" and inches == "":
            return return_val

        feet_val = feet
        inches_val = inches
        if feet_val == "":
            feet_val = "0"
        if inches == "":
            inches_val = "0"

        if "." in feet_val and not feet_val.endswith(".0"):
            feet_decimal = Decimal(feet_val)
            inches_decimal = feet_decimal * 12
            return_val = str(round(inches_decimal, 2))
        else:
            return_val = str(round((Decimal(feet_val) * 12) + Decimal(inches_val), 2))

        if return_val.endswith(".00"):
            return_val = return_val.split(".")[0]
        elif return_val.endswith("0"):
            return_val = return_val[:-1]
        return return_val


    def make_csv(self):
        headers = [
            "id",
            "patient",
            "pulse",
            "height",
            "weight_oz",
            "weight_lbs",
            "pulse_rhythm",
            "body_temperature",
            "respiration_rate",
            "oxygen_saturation",
            "waist_circumference",
            "body_temperature_site",
            "blood_pressure_systole",
            "blood_pressure_diastole",
            "blood_pressure_position_and_site",
            "created_by",
            "created_at",
            "comment",
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for patient in data:
                patient_id = patient["patient_id"]
                for vital_entry in patient["vitals"]:

                    note = ""
                    pulse = None
                    height = None
                    weight_oz = None
                    weight_lbs = None
                    pulse_rhythm = ""
                    body_temperature = None
                    respiration_rate = None
                    oxygen_saturation = None
                    waist_circumference = None
                    body_temperature_site = ""
                    blood_pressure_systole = None
                    blood_pressure_diastole = None
                    blood_pressure_position_and_site = ""

                    height_feet = [v for v in vital_entry["vitals"] if v["vital_name"] == "Height" and v["vital_unit"] == "ft"]
                    height_inches = [v for v in vital_entry["vitals"] if v["vital_name"] == "Height" and v["vital_unit"] == "ins"]
                    if height_feet:
                        height_feet = height_feet[0]["vital_value"]
                    else:
                        height_feet = ""

                    if height_inches:
                        height_inches = height_inches[0]["vital_value"]
                    else:
                        height_inches = ""

                    height = self.convert_height_feet_and_inches_to_inches(height_feet, height_inches)

                    pulse_rhythm_dict = {
                        "regular": "0",
                        "irregularly irregular": "1",
                        "regularly_irregular": "2"

                    }

                    # entry_date is in the US/Central time zone (looking at corresponding encounter data)
                    created_at = arrow.get(vital_entry["entry_date"]).replace(tzinfo="US/Central").isoformat()

                    for vital in vital_entry["vitals"]:
                        vital_name = vital["vital_name"]
                        vital_unit = vital["vital_unit"]
                        vital_value = vital["vital_value"]

                        if vital_value != "":
                            if vital_name == "Weight" and vital_unit == "lbs":
                                weight_lbs = vital_value
                                if weight_lbs.endswith(".0"):
                                    weight_lbs = vital_value.split(".")[0]
                            elif vital_name == "Weight" and vital_unit == "ozs":
                                weight_oz = vital_value
                                if weight_oz.endswith(".0"):
                                    weight_oz = vital_value.split(".")[0]
                            elif vital_name == "Temp":
                                body_temperature = vital_value
                            elif vital_name == "Height":
                                # already handled above
                                pass
                            elif vital_name == "SPO2":
                                oxygen_saturation = int(vital_value.split(".")[0]) # there are no decimal vals in this field (all xx.0)
                            elif vital_name == "Systolic BP":
                                blood_pressure_systole = int(vital_value.split(".")[0])
                            elif vital_name == "Diastolic BP":
                                blood_pressure_diastole = int(vital_value.split(".")[0])
                            elif vital_name == "Pulse Rate":
                                pulse = int(vital_value.split(".")[0])
                            elif vital_name == "Pulse Pattern":
                                pulse_rhythm = pulse_rhythm_dict.get(vital_value.lower(), "")
                            else:
                                pass

                    row_to_write = {
                        "id": vital_entry["vital_entry_id"],
                        "patient": patient_id,
                        "pulse": pulse,
                        "height": height,
                        "weight_oz" : weight_oz,
                        "weight_lbs": weight_lbs,
                        "pulse_rhythm": pulse_rhythm,
                        "body_temperature": body_temperature,
                        "respiration_rate": respiration_rate,
                        "oxygen_saturation": oxygen_saturation,
                        "waist_circumference": waist_circumference,
                        "body_temperature_site": body_temperature_site,
                        "blood_pressure_systole": blood_pressure_systole,
                        "blood_pressure_diastole": blood_pressure_diastole,
                        "blood_pressure_position_and_site": blood_pressure_position_and_site,
                        "created_by": "",
                        "created_at": created_at,
                        "comment": note,
                    }
                    writer.writerow(row_to_write)

        print(f"Sucessfully created {self.csv_file}")


    def validate(self, delimiter=","):
        validated_rows = []
        errors = defaultdict(list)

        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            validate_header(reader.fieldnames,
                accepted_headers = {
                    "id",
                    "patient",
                    "pulse",
                    "height",
                    "weight_oz",
                    "weight_lbs",
                    "pulse_rhythm",
                    "body_temperature",
                    "respiration_rate",
                    "oxygen_saturation",
                    "waist_circumference",
                    "body_temperature_site",
                    "blood_pressure_systole",
                    "blood_pressure_diastole",
                    "blood_pressure_position_and_site",
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

            provider_key = "5eede137ecfe4124b8b773040e33be14" # canvas-bot - no providers in the data

            vitals_values = {
                "pulse": int(row["pulse"]) if row["pulse"] else None,
                "height": row["height"] if row["height"] else None,
                "weight_oz" : row["weight_oz"] if row["weight_oz"] else None,
                "weight_lbs": row["weight_lbs"] if row["weight_lbs"] else None,
                "pulse_rhythm": row["pulse_rhythm"],
                "body_temperature": row["body_temperature"] if row["body_temperature"] else None,
                "respiration_rate": int(row["respiration_rate"]) if row["respiration_rate"] else None,
                "oxygen_saturation": int(row["oxygen_saturation"]) if row["oxygen_saturation"] else None,
                "waist_circumference": row["waist_circumference"] if row["waist_circumference"] else None,
                "body_temperature_site": row["body_temperature_site"],
                "blood_pressure_systole": int(row["blood_pressure_systole"]) if row["blood_pressure_systole"] else None,
                "blood_pressure_diastole": int(row["blood_pressure_diastole"]) if row["blood_pressure_diastole"] else None,
                "blood_pressure_position_and_site": row["blood_pressure_position_and_site"],
                "comment": row["comment"],
            }

            try:
                vitals_import_note = self.create_note(
                    canvas_patient_key=patient_key,
                    note_type_name="Vitals Data Import",
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

    def get_unvalidated_command_data(self):
        staged_commands_uuid_list = [
            # populate with commands that didn't validate/ are still staged
        ]

        output_headers = [
            "Charm Patient ID",
            "Canvas Patient ID",
            "Charm Vital Entry ID",
            "Date of Entry",
            "Vital Name",
            "Vital Value",
            "Vital Units",
        ]

        charm_ids = {}
        done_rows = fetch_from_csv(self.done_file, key="canvas_command_id", delimiter="|")
        for unvalidated_command_uuid in staged_commands_uuid_list:
            done_row = done_rows[unvalidated_command_uuid]
            charm_ids[done_row[0]["id"]] = done_row[0]["patient_key"]


        output_rows = []
        vitals_json = fetch_from_json(self.json_file)
        for patient_vitals in vitals_json:
            charm_patient_id = patient_vitals["patient_id"]
            for p_vital in patient_vitals["vitals"]:
                # is in the list of unvalidated entries
                if p_vital["vital_entry_id"] in charm_ids:
                    charm_vital_entry_id = p_vital["vital_entry_id"]
                    charm_entry_date = p_vital["entry_date"]
                    for v in p_vital["vitals"]:
                        if v["vital_value"]:
                            vital_name = v["vital_name"]
                            vital_value = v["vital_value"]
                            vital_unit = v["vital_unit"]
                            bad_value = False

                            if vital_unit == "lbs" and not is_number(vital_value):
                                bad_value = True

                            elif vital_unit == "lbs" and (int(float(vital_value)) < 1 or int(float(vital_value)) > 1500):
                                bad_value = True

                            elif vital_unit == "ft" and (int(float(vital_value))*12 < 10 or int(float(vital_value))*12 > 108):
                                bad_value = True

                            elif vital_unit == "ins" and int(float(vital_value)) > 108:
                                bad_value = True

                            elif vital_unit == "F" and (int(float(vital_value)) < 85 or int(float(vital_value)) > 107):
                                bad_value = True

                            output_row = {
                                "Charm Patient ID": charm_patient_id,
                                "Canvas Patient ID": charm_ids[charm_vital_entry_id],
                                "Charm Vital Entry ID": charm_vital_entry_id,
                                "Date of Entry": charm_entry_date,
                                "Vital Name": vital_name,
                                "Vital Value": vital_value,
                                "Vital Units": vital_unit,
                            }
                            if bad_value:
                                output_rows.append(output_row)
        with open("results/out_of_range_vitals.csv", "w") as fhandle:
            writer = csv.DictWriter(fhandle, fieldnames=output_headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in output_rows:
                writer.writerow(row)


    def get_command_ids_to_fix(self):
        description_lookup = {
            "Height": "height",
            "Weight": "weight_lbs",
            "Temp": "body_temperature",
        }

        update_vitals = []
        done_dict = fetch_from_csv(self.done_file, key="id", delimiter="|")
        with open("PHI/out_of_range_vitals.csv") as fhandle:
            reader = csv.DictReader(fhandle, delimiter=",")
            for row in reader:
                done_row = done_dict[row["Charm Vital Entry ID"]]
                canvas_command_id = done_row[0]["canvas_command_id"]
                update_vitals.append(
                    {
                        "command_id": canvas_command_id,
                        "clear_field": description_lookup[row["Vital Name"]],
                        "update_field": {
                            "field_name": description_lookup[row["Revised_Vital_Name"]],
                            "value": row["Revised_Vital_Value"]
                        }
                    }
                )
        print(json.dumps(update_vitals))
        return update_vitals


    def commit_and_lock(self):
        commit_list = [
            # populate with command ids that need committing after validation fixes
        ]

        for command_id in commit_list:
            self.commit_command(command_id)
            print(f"committed command id {command_id}")

        lock_list = [
            # populate with note keys that need locking after validation fixes
        ]

        for vitals_note in lock_list:
            self.perform_note_state_change(vitals_note, state='LKD')
            print(f"locked note {vitals_note}")



if __name__ == "__main__":
    loader = VitalsLoader(environment='ways2well')
    # loader.make_json()
    # loader.make_csv()
    # valid_rows = loader.validate()
    # loader.load(valid_rows)
    # loader.get_unvalidated_command_data()

    # loader.get_command_ids_to_fix()
    # loader.commit_and_lock()
