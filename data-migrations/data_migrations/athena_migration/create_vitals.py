import arrow
from decimal import Decimal

from data_migrations.template_migration.vitals import VitalsMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
)


class VitalsLoader(VitalsMixin):
    def __init__(self, environment) -> None:
        self.json_file = "PHI/vitals.json"
        self.csv_file = "PHI/vitals.csv"
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)
        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.error_file = 'results/errored_vitals.csv'
        self.done_file = 'results/done_vitals.csv'
        self.ignore_file = 'results/ignored_vitals.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.validation_error_file = "results/PHI/errored_vitals_validation.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.default_note_type_name = "Athena Historical Note"

        super().__init__()

    def make_patient_vitals_dict(self):
        data = fetch_from_json(self.json_file)

        patient_vitals_dict = {}

        # elements that are in the file:

        # VITALS.BLOODPRESSURE.DIASTOLIC
        # VITALS.BLOODPRESSURE.DIASTOLICREFUSED
        # VITALS.BLOODPRESSURE.REFUSED
        # VITALS.BLOODPRESSURE.REFUSEDREASON
        # VITALS.BLOODPRESSURE.SITE
        # VITALS.BLOODPRESSURE.SYSTOLIC
        # VITALS.BLOODPRESSURE.SYSTOLICREFUSED
        # VITALS.BLOODPRESSURE.TYPE
        # VITALS.BLOODSUGAR
        # VITALS.BMI
        # VITALS.BMI.PERCENTILE
        # VITALS.BMI.REFUSED
        # VITALS.HEADCIRCUMFERENCE
        # VITALS.HEIGHT
        # VITALS.HEIGHT.REFUSED
        # VITALS.HEIGHT.REFUSEDREASON
        # VITALS.HEIGHT.TYPE
        # VITALS.NOTES
        # VITALS.O2SATURATION
        # VITALS.O2SATURATION.AIRTYPE
        # VITALS.PULSE.RATE
        # VITALS.WAISTCIRCUMFERENCE
        # VITALS.WEIGHT
        # VITALS.WEIGHT.OUTOFRANGE
        # VITALS.WEIGHT.REFUSED
        # VITALS.WEIGHT.REFUSEDREASON
        # VITALS.WEIGHT.TYPE

        relevant_elements = {
            "VITALS.HEIGHT",
            "VITALS.WEIGHT",
            "VITALS.BLOODPRESSURE.DIASTOLIC",
            "VITALS.BLOODPRESSURE.SYSTOLIC",
            "VITALS.PULSE.RATE",
            "VITALS.O2SATURATION",
            "VITALS.NOTES",
            "VITALS.WAISTCIRCUMFERENCE",
        }

        for row in data:
            patient_id = row["patientdetails"]["enterpriseid"]
            if patient_id not in patient_vitals_dict:
                patient_vitals_dict[patient_id] = {"ENCOUNTER": {}, "FLOWSHEET": {}}

            for patient_vitals in row["vitals"]:
                for reading_list in patient_vitals["readings"]:
                    for reading_dict in reading_list:
                        reading_source = reading_dict["source"]
                        source_id = reading_dict["sourceid"]
                        reading_id = reading_dict["readingid"]
                        if reading_dict["clinicalelementid"] in relevant_elements:
                            if source_id not in patient_vitals_dict[patient_id][reading_source]:
                                patient_vitals_dict[patient_id][reading_source][source_id] = {"readings": {reading_id: {"values": {reading_dict["clinicalelementid"]: {"value": reading_dict["value"], "unit": reading_dict.get("unit", ""), "vital_id": reading_dict["vitalid"], "createdby": reading_dict["createdby"]}}}}, "date": reading_dict["readingtaken"]}
                            else:
                                if reading_id not in patient_vitals_dict[patient_id][reading_source][source_id]["readings"]:
                                    patient_vitals_dict[patient_id][reading_source][source_id]["readings"][reading_id] = {"values": {reading_dict["clinicalelementid"]: {"value": reading_dict["value"], "unit": reading_dict.get("unit", ""), "vital_id": reading_dict["vitalid"], "createdby": reading_dict["createdby"]}}}
                                else:
                                    patient_vitals_dict[patient_id][reading_source][source_id]["readings"][reading_id]["values"][reading_dict["clinicalelementid"]] = {"value": reading_dict["value"], "unit": reading_dict.get("unit", ""), "vital_id": reading_dict["vitalid"], "createdby": reading_dict["createdby"]}
        return patient_vitals_dict

    def cm_to_inches(self, centimeters):
        cms_str = str(round(Decimal(centimeters) / Decimal("2.54"), 1))
        if cms_str.endswith(".0"):
            return cms_str.split(".")[0]
        return cms_str

    def gm_to_lbs_oz(self, grams):
        if grams == "0":
            return "0", "0"
        pounds = str(Decimal(grams) * Decimal("0.0022046226"))
        pounds_str = pounds.split(".")[0]
        decimal_portion = "." + pounds.split(".")[1]
        ounces_str = str(round(Decimal(decimal_portion) * Decimal("16"), 0))
        if ounces_str == "16":
            return str(int(pounds_str) + 1), 0
        return pounds_str, ounces_str


    def validate(self, patient_vitals_dict):
        reading_sources = ["ENCOUNTER", "FLOWSHEET",]
        for patient_id, vitals_readings in patient_vitals_dict.items():
            if not patient_id:
                raise ValueError("No patient ID present")
            for src in reading_sources:
                patient_readings = vitals_readings[src]
                source_ids = patient_readings.keys()
                for src_id in source_ids:
                    if not src_id:
                        raise ValueError("No source ID present")
                    date_taken = patient_readings[src_id]["date"]
                    if not date_taken:
                        raise ValueError(f"No date_taken present for source ID {src_id}")

    def load(self, patient_vitals_dict):
        ids = set()
        reading_sources = ["ENCOUNTER", "FLOWSHEET",]

        already_loaded = 0
        not_loaded = 0
        patient_not_mapped = 0
        vitals_import_note_count = 0
        # this is just to get the count
        for patient_id, vitals_readings in patient_vitals_dict.items():
            for src in reading_sources:

                patient_readings = vitals_readings[src]
                source_ids = patient_readings.keys()
                for src_id in source_ids:
                    vitals_import_note_count += 1
                    unique_import_note_id = f"{src}~{src_id}"

                    if patient_id not in self.patient_map:
                        patient_not_mapped += 1
                    if unique_import_note_id in self.done_records:
                        already_loaded += 1
                    else:
                        not_loaded += 1
        print(f"Loaded: {already_loaded}")
        print(f"Not Loaded: {not_loaded}")
        print(f"Patient not mapped: {patient_not_mapped}")
        ####

        vitals_notes_counter = 1
        for patient_id, vitals_readings in patient_vitals_dict.items():
            for src in reading_sources:
                patient_readings = vitals_readings[src]
                source_ids = patient_readings.keys()
                for src_id in source_ids:

                    print(f"On {vitals_notes_counter} of {vitals_import_note_count} vitals import notes")
                    vitals_notes_counter += 1

                    date_taken = patient_readings[src_id]["date"]
                    unique_import_note_id = f"{src}~{src_id}"

                    patient_key = ""
                    try:
                        patient_key = self.map_patient(patient_id)
                    except BaseException as e:
                        pass

                    if patient_key:
                        if unique_import_note_id in ids or unique_import_note_id in self.done_records:
                            print(' Already did note record')
                            continue

                        try:
                            vitals_import_note = self.create_note(
                                note_type_name="Vitals Data Import",
                                canvas_patient_key=patient_key,
                                provider_key="5eede137ecfe4124b8b773040e33be14", # canvas-bot
                                encounter_start_time=arrow.get(date_taken, "MM/DD/YYYY").replace(tzinfo="America/New York").shift(hours=12).isoformat(),
                                practice_location_key=self.default_location
                            )
                            self.done_row(f"{unique_import_note_id}|{patient_id}|{patient_key}||{vitals_import_note}")
                            ids.add(unique_import_note_id)
                        except Exception as e:
                            self.error_row(f"{unique_import_note_id}|{patient_id}|{patient_key}", e)
                            continue

                        for reading_id, readings in patient_readings[src_id]["readings"].items():
                            values_dict = readings["values"]
                            unique_command_id = f"{src}~{src_id}~{reading_id}"

                            height_dict = values_dict.get("VITALS.HEIGHT")
                            if height_dict:
                                if height_dict.get("unit") == "cm":
                                    height = self.cm_to_inches(height_dict["value"])
                                else:
                                    raise ValueError("unexpected height unit")
                            else:
                                height = ""

                            weight_dict = values_dict.get("VITALS.WEIGHT")
                            if weight_dict:
                                if weight_dict.get("unit") == "g":
                                    weight_lbs, weight_oz = self.gm_to_lbs_oz(weight_dict["value"])
                                else:
                                    raise ValueError("unexpected weight unit")
                            else:
                                weight_lbs, weight_oz = "", ""

                            bp_systolic_dict = values_dict.get("VITALS.BLOODPRESSURE.SYSTOLIC")
                            if bp_systolic_dict:
                                bp_systolic = bp_systolic_dict["value"]
                            else:
                                bp_systolic = ""

                            bp_diastolic_dict = values_dict.get("VITALS.BLOODPRESSURE.DIASTOLIC")
                            if bp_diastolic_dict:
                                bp_diastolic = bp_diastolic_dict["value"]
                            else:
                                bp_diastolic = ""

                            # only record blood pressure if it is a full reading (top and bottom numbers)
                            if not all([bp_systolic, bp_diastolic,]):
                                bp_systolic = ""
                                bp_diastolic = ""

                            pulse_dict = values_dict.get("VITALS.PULSE.RATE")
                            if pulse_dict:
                                pulse = pulse_dict["value"]
                            else:
                                pulse = ""

                            o2_dict = values_dict.get("VITALS.O2SATURATION")
                            if o2_dict:
                                o2_saturation = o2_dict["value"]
                            else:
                                o2_saturation = ""

                            waist_circumference_dict = values_dict.get("VITALS.WAISTCIRCUMFERENCE")
                            if waist_circumference_dict:
                                if waist_circumference_dict.get("unit") == "cm":
                                    waist_circumference = self.cm_to_inches(waist_circumference_dict["value"])
                                else:
                                    raise ValueError("unexpected waist circumference unit")
                            else:
                                waist_circumference = ""


                            notes_dict = values_dict.get("VITALS.NOTES")
                            if notes_dict:
                                reading_notes = notes_dict["value"]
                            else:
                                reading_notes = ""

                            if src == "FLOWSHEET":
                                if not reading_notes:
                                    reading_notes = "device-generated"
                                else:
                                    reading_notes = f"device-generated\n{reading_notes}"

                            vitals_values = {
                                "note": reading_notes,
                                "height": height,
                                "weight_oz": weight_oz,
                                "weight_lbs": weight_lbs,
                                "pulse": pulse,
                                "pulse_rhythm": "", # not in data
                                "body_temperature": "", # not in data
                                "respiration_rate": "", # not in data
                                "oxygen_saturation": o2_saturation,
                                "waist_circumference": waist_circumference,
                                "body_temperature_site": "", # not in data
                                "blood_pressure_systole": bp_systolic,
                                "blood_pressure_diastole": bp_diastolic,
                                "blood_pressure_position_and_site": ""
                            }

                            vitals_payload = {
                                "noteKey": vitals_import_note,
                                "schemaKey": "vitals",
                                "values": vitals_values,
                            }

                            if unique_command_id in ids or unique_command_id in self.done_records:
                                print(' Already did command record')
                                continue

                            try:
                                command_id = self.create_command(vitals_payload)
                                self.done_row(f"{unique_command_id}|{patient_id}|{patient_key}|{command_id}|")
                                ids.add(unique_command_id)
                            except BaseException as e:
                                self.error_row(f"{unique_command_id}|{patient_id}|{patient_key}", e)
                                continue

                            try:
                                self.commit_command(command_id)
                            except BaseException as e:
                                self.error_row(f"{unique_command_id}|{patient_id}|{patient_key}", e)

                        # now lock the Vitals Import note
                        try:
                            self.perform_note_state_change(vitals_import_note, state='LKD')
                        except Exception as e:
                            self.error_row(f"{unique_import_note_id}|{patient_id}|{patient_key}", e)
                    else:
                        self.ignore_row(f"{src}~{src_id}", "Ignoring due to no patient map")



if __name__ == "__main__":
    loader = VitalsLoader('phi-test-accomplish')
    patient_vitals_dict = loader.make_patient_vitals_dict()
    loader.validate(patient_vitals_dict)
    loader.load(patient_vitals_dict)
