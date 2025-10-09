import csv, json
from copy import deepcopy

from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.utils import (
    fetch_from_json, write_to_json,
    load_fhir_settings,
    fetch_complete_csv_rows,
    fetch_from_csv,
)


class MedicationLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/supplements.json"
        self.csv_file = "PHI/supplements.csv"
        self.fumage_helper = load_fhir_settings(environment)

        self.ignore_file = "results/ignored_supplements.csv"
        self.done_file = "results/done_supplements.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = "results/errored_supplements.csv"
        self.error_records = fetch_complete_csv_rows(self.error_file)
        self.validation_error_file = "results/PHI/errored_supplement_validation.json"
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.default_note_type_name = "Charm Historical Note"

    def make_json_file(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]
        supplement_list = charm_patient_api.fetch_supplements(patient_ids=patient_ids)
        write_to_json(self.json_file, supplement_list)

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "Medication Name",
            "SIG",
            "Original Code",
        ]

        data = fetch_from_json(self.json_file)

        # using this to dedupe
        patient_supplements = {}

        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(
                fhandle,
                fieldnames=headers,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()
            for supplement in data:
                status = "active" if str(supplement["status"]) == "1" and not supplement["end_date"] else "stopped"
                sig_items = [
                    supplement["dosage"],
                    supplement["dosage_unit"],
                    supplement["frequency"],
                    supplement["intake_type"],
                ]
                sig_items = [i for i in sig_items if i]
                sig = " ".join(sig_items)
                if supplement["comments"]:
                    if sig:
                        sig = f"{sig}; {supplement['comments']}"
                    else:
                        sig = supplement["comments"]

                supplement_name = f"SUPP_{supplement['supplement_name']}"
                if supplement["strength"]:
                    supplement_name = f"{supplement_name}, Strength {supplement['strength']}"
                if supplement["dosage_form"]:
                    supplement_name = f"{supplement_name}, {supplement['dosage_form']}"
                if supplement["route"]:
                    supplement_name = f"{supplement_name}, {supplement['route']}"

                row_to_write = {
                    "ID": supplement["patient_supplement_id"],
                    "Patient Identifier": supplement["patient_id"],
                    "Status": status,
                    "RxNorm/FDB Code": "unstructured",
                    "Medication Name": supplement_name,
                    "SIG": sig,
                    "Original Code": "",
                }

                if supplement["patient_id"] not in patient_supplements:
                    patient_supplements[supplement["patient_id"]] = [row_to_write]
                else:
                    # check if an exact entry exists in the patient medication list already
                    patient_meds_copy = deepcopy(patient_supplements[supplement["patient_id"]])
                    row_copy = deepcopy(row_to_write)
                    del row_copy["ID"]
                    for med in patient_meds_copy:
                        # dupes will have different IDs, so remove it for the comparison
                        del med["ID"]
                    patient_meds_copy = [json.dumps(m, sort_keys=True) for m in patient_meds_copy]
                    if json.dumps(row_copy, sort_keys=True) not in patient_meds_copy:
                        patient_supplements[supplement["patient_id"]].append(row_to_write)
                    else:
                        self.ignore_row(supplement['patient_supplement_id']," Ignoring due to duplicate patient supplement")

            for ps in patient_supplements.values():
                for p in ps:
                    writer.writerow(p)

        print(f"Successfully created {self.csv_file}")

    def look_up_error_rows(self):
        lookup_dict = {}
        errored_records = fetch_from_csv(self.error_file, key="id", delimiter="|")
        data = fetch_from_json(self.json_file)
        for id, row in errored_records.items():
            lookup_dict[id] = {"patient_key": row[0]["canvas_patient_key"]}

        for supplement in data:
            if supplement["patient_supplement_id"] in lookup_dict:
                sig_items = [
                    supplement["dosage"],
                    supplement["dosage_unit"],
                    supplement["frequency"],
                    supplement["intake_type"],
                ]
                sig_items = [i for i in sig_items if i]
                sig = " ".join(sig_items)
                if supplement["comments"]:
                    if sig:
                        sig = f"{sig}; {supplement['comments']}"
                    else:
                        sig = supplement["comments"]

                supplement_name = f"SUPP_{supplement['supplement_name']}"
                if supplement["strength"]:
                    supplement_name = f"{supplement_name}, Strength {supplement['strength']}"
                if supplement["dosage_form"]:
                    supplement_name = f"{supplement_name}, {supplement['dosage_form']}"
                if supplement["route"]:
                    supplement_name = f"{supplement_name}, {supplement['route']}"


                lookup_dict[supplement["patient_supplement_id"]]["sig"] = sig
                lookup_dict[supplement["patient_supplement_id"]]["name"] = supplement_name

        return lookup_dict


if __name__ == "__main__":
    loader = MedicationLoader(environment="ways2well")
    # loader.make_csv()

    valid_rows = loader.validate(delimiter=",")
    loader.load(valid_rows)
