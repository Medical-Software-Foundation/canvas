import csv
import arrow

from data_migrations.template_migration.allergy import AllergyLoaderMixin
from data_migrations.utils import (
    fetch_from_json,
    load_fhir_settings,
    write_to_json,
    fetch_complete_csv_rows
)
from data_migrations.charm_migration.utils import CharmFHIRAPI, CharmPatientAPI
from data_migrations.template_migration.utils import FileWriterMixin


class AllergyLoader(AllergyLoaderMixin, FileWriterMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.csv_file = "PHI/allergies.csv"
        self.json_file = "PHI/allergies.json"
        self.allergy_map_file = "mappings/allergy_coding_map.json"
        self.allergy_map = fetch_from_json(self.allergy_map_file)
        self.patient_api_json_file = "PHI/allergies_patient_api.json"
        self.fhir_api_json_file = "PHI/allergies_fhir_api.json"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.done_file = 'results/done_allergies.csv'
        self.done_questionnaire_file = 'results/done_questionnaire_allergies.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_allergies.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_allergies.csv'
        self.error_questionnaire_file = 'results/errored_questionnaire_allergies.csv'
        self.fumage_helper = load_fhir_settings(environment)
        self.validation_error_file = "results/PHI/errored_allergy_validation.json"

        self.allergy_map_file = "mappings/allergy_coding_map.json"

        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.default_note_type_name = "Charm Historical Note"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        super().__init__()

    def make_patient_api_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_ids = list(self.patient_map.keys())
        allergy_list = charm_patient_api.fetch_allergies(patient_ids=patient_ids)
        write_to_json(self.patient_api_json_file, allergy_list)

    def make_fhir_api_json(self):
        charm_fhir_api = CharmFHIRAPI(environment=self.environment)
        fhir_allergies = charm_fhir_api.fetch_allergies()
        write_to_json(self.fhir_api_json_file, fhir_allergies)

    def make_json(self):
        # combines the Patient API data with codings from the FHIR API
        output = []
        patient_api_data = fetch_from_json(self.patient_api_json_file)
        fhir_api_data = fetch_from_json(self.fhir_api_json_file)

        allergy_id_coding_map = {}
        for f_allergy in fhir_api_data:
            if codings := f_allergy["resource"].get("code", {}).get("coding"):
                allergy_id_coding_map[f_allergy["resource"]["id"]] = codings

        for p_allergy in patient_api_data:
            p_allergy["codings"] = allergy_id_coding_map.get(p_allergy["patient_allergy_id"], [])
            output.append(p_allergy)
        write_to_json(self.json_file, output)

    def make_allergy_map_file(self):
        allergy_map = {}
        allergy_data = fetch_from_json(self.json_file)
        for allergy in allergy_data:
            rx_norm_code = ""
            rx_norm_codes = [c["code"] for c in allergy["codings"] if "rxnorm" in c["system"]]
            if rx_norm_codes:
                rx_norm_code = rx_norm_codes[0]

            if allergy["allergen"] not in allergy_map:
                allergy_map[f"{allergy['allergen']}|{rx_norm_code}"] = []
        write_to_json(self.allergy_map_file, allergy_map)


    def make_csv(self):
        data = fetch_from_json(self.json_file)

        headers = [
            "ID",
            "Patient Identifier",
            "Clinical Status",
            "Type",
            "FDB Code",
            "Name",
            "Onset Date",
            "Free Text Note",
            "Reaction",
            "Recorded Provider",
            "Severity",
            "Original Name",
        ]

        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(
                fhandle,
                fieldnames=headers,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()
            for row in data:
                rx_norm_code = ""
                rx_norm_codes = [c["code"] for c in row["codings"] if "rxnorm" in c["system"]]
                if rx_norm_codes:
                    rx_norm_code = rx_norm_codes[0]

                mapping_key = f"{row["allergen"].lower()}|{rx_norm_code}"
                fdb_map = self.allergy_map.get(mapping_key)

                fdb_code = ""
                fdb_display = ""

                if fdb_map is None:
                    self.ignore_row(row["patient_allergy_id"], f"Ignoring due to not finding FDB mapping for {mapping_key}")
                    continue
                elif fdb_map == "DO_NOT_MIGRATE":
                    self.ignore_row(row["patient_allergy_id"], f"Ignoring due to being on the DO_NOT_MIGRATE list - {mapping_key}")
                    continue
                elif fdb_map == "UNSTRUCTURED":
                    fdb_code = "1-143"
                    fdb_display = "No Allergy Information Available"
                elif type(fdb_map) is dict:
                        fdb_code = fdb_map["code"]
                        fdb_display = fdb_map["display"]
                elif type(fdb_map) is list:
                    fdb_code = fdb_map[0]["code"]
                    fdb_display = fdb_map[0]["display"]
                else:
                    raise ValueError("Unexpected mapping detected")

                severity = row["severity"].lower()
                if severity not in ["mild", "moderate", "severe"]:
                    severity = ""

                row_to_write = {
                    "ID": row["patient_allergy_id"],
                    "Patient Identifier": row["patient_id"],
                    "Clinical Status": "active" if str(row["status"]) == '1' else "inactive",
                    "Type": "allergy",
                    "FDB Code": fdb_code,
                    "Name": fdb_display,
                    "Onset Date": row["date_of_entry"],
                    "Free Text Note": "",
                    "Reaction": row["reactions"],
                    "Recorded Provider": "",
                    "Severity": severity,
                    "Original Name": row["allergen"],
                }

                writer.writerow(row_to_write)

        print(f"Successfully created {self.csv_file}")

    def load_unstructured_as_questionnaire_response(self, valid_rows):
        done_questionnaire_records = fetch_complete_csv_rows(self.done_questionnaire_file)
        ids = set()

        for row in valid_rows:
            if row["ID"] in ids or row["ID"] in done_questionnaire_records:
                print("Already did record - continuing")
                continue

            fdb_code = row["FDB Code"]
            patient_key = self.patient_map.get(row["Patient Identifier"])

            if patient_key and fdb_code == "1-143":
                historical_note_id = self.get_or_create_historical_data_input_note(patient_key)

                payload = {
                    "resourceType": "QuestionnaireResponse",
                    "extension": [
                        {
                            "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                            "valueId": historical_note_id
                        }
                    ],
                    "questionnaire": "Questionnaire/645efdef-a47f-4fc5-804c-055ae7aa0bf1", # Historical Allergies
                    "status": "in-progress",
                    "subject": {
                        "reference": f"Patient/{patient_key}",
                        "type": "Patient"
                    },
                    "authored": arrow.now().date().isoformat() + "T12:00:00-05:00",
                    "author": {
                        "reference": "Practitioner/5eede137ecfe4124b8b773040e33be14", # canvas-bot
                        "type": "Practitioner"
                    },
                    "item": [
                        {
                            "linkId": "81f8a506-08de-449e-9aee-6e668490351a",
                            "answer": [
                                {
                                    "valueString": row["Original Name"]
                                }
                            ]
                        }
                    ]
                }

                try:
                    canvas_id = self.fumage_helper.perform_create(payload)
                    self.done_row(f"{row['ID']}|{row["Patient Identifier"]}|{patient_key}|{canvas_id}|{fdb_code}", file=self.done_questionnaire_file)
                    ids.add(row["ID"])
                except BaseException as e:
                    self.error_row(f"{row['ID']}|{row["Patient Identifier"]}|{patient_key}", e, file=self.error_questionnaire_file)



if __name__ == "__main__":
    allergy_loader = AllergyLoader("ways2well")
    # allergy_loader.make_patient_api_json()
    # allergy_loader.make_fhir_api_json()
    # allergy_loader.make_json()
    # allergy_loader.make_allergy_map_file()

    # allergy_loader.make_csv()

    valid_rows = allergy_loader.validate(delimiter=",")
    # allergy_loader.load(valid_rows)
    allergy_loader.load_unstructured_as_questionnaire_response(valid_rows)
