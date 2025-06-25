import csv, os

from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.utils import fetch_from_json, write_to_json, load_fhir_settings, fetch_complete_csv_rows


class MedicationLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/medications.json"
        self.csv_file = 'PHI/medications.csv'
        self.fumage_helper = load_fhir_settings(environment)
        self.med_mapping_file = "mappings/medication_coding_map.json"
        self.med_mapping = fetch_from_json(self.med_mapping_file)
        self.ignore_file = "results/ignored_medications.csv"
        self.done_file = "results/done_medications.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = "results/errored_medications.csv"
        self.validation_error_file = "results/PHI/errored_medication_validation.json"
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.default_note_type_name = "Athena Historical Note"

    def make_fdb_mapping(self, delimiter='|'):
        data = fetch_from_json(self.json_file)
        fdb_mapping_dict = {}
        for row in data:
            for med in row["medicationrequests"]:
                if "medicationReference" in med and "display" in med["medicationReference"]:
                    key = f"{med["medicationReference"]["display"]}|"
                    if key not in fdb_mapping_dict:
                        fdb_mapping_dict[key] = []
        write_to_json(self.med_mapping_file, fdb_mapping_dict)


    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Status",
            "RxNorm/FDB Code",
            "SIG",
            "Medication Name",
            "Original Code",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            data = fetch_from_json(self.json_file)

            for row in data:
                for medication in row.get("medicationrequests", []):
                    medication_id = medication.get("id", "").replace("a-25828.", "")
                    patient_id = medication.get("subject", {}).get("reference", "").replace("Patient/a-25828.E-", "")
                    status = medication.get("status", "")
                    medication_name = medication.get("medicationReference", {}).get("display", "")

                    if not medication_name:
                        self.ignore_row(medication_id, "Ignoring row due to no medication name.")
                        continue

                    if status in ["entered-in-error", "cancelled", "draft"]:
                        self.ignore_row(medication_id, f"Ignoring due to status of {status}")
                        continue

                    if status in ["completed", "stopped", ""]:
                        status = "stopped"

                    mapping_found = self.med_mapping.get(f"{medication_name}|")
                    if mapping_found:
                        code = next(item['code'] for item in mapping_found if item["system"] == 'http://www.fdbhealth.com/')
                        if not code:
                            code = "unstructured"
                    else:
                        print(f"Unstructured for {medication_name}")
                        code = "unstructured"

                    row_to_write = {
                        "ID": medication_id,
                        "Patient Identifier": patient_id,
                        "Status": status,
                        "RxNorm/FDB Code": code,
                        "SIG": medication["dosageInstruction"][0].get("text", "").replace("\n", "\\n") if medication.get("dosageInstruction") else "",
                        "Medication Name": medication_name,
                        "Original Code": "",
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")

    def dedupe(self, valid_rows):
        # There are a lot of duplicate medications. In order to not have multiple show up in the chart,
        # we will dedupe duplicate records.
        dupe_count = 0
        dupe_dict = {}
        return_rows = []
        for row in valid_rows:
            dupe_key = f"{row["Patient Identifier"]}|{row["Status"]}|{row["RxNorm/FDB Code"]}|{row["SIG"]}|{row["Medication Name"]}"
            if dupe_key not in dupe_dict:
                dupe_dict[dupe_key] = [row]
            else:
                dupe_dict[dupe_key].append(row)

        for key, row_list in dupe_dict.items():
            if len(row_list) > 1:
                # only keep the one with the lowest ID; ignore the rest
                sorted_list = sorted(row_list, key=lambda med_list: med_list["ID"])
                return_rows.append(sorted_list[0])
                for med in sorted_list[1:]:
                    dupe_count += 1
                    self.ignore_row(row["ID"], "Ignoring because record is a duplicate.")
            else:
                return_rows.append(row_list[0])
        print(f"valid_rows was {len(valid_rows)} rows long")
        print(f"Removed {dupe_count} duplicate records")
        print(f"Returning {len(return_rows)} rows")
        return return_rows

if __name__ == "__main__":
    loader = MedicationLoader(environment="phi-test-accomplish")
    loader.make_csv()
    # loader.make_fdb_mapping()
    # loader.map()

    valid_rows = loader.validate(delimiter=",")
    valid_rows = loader.dedupe(valid_rows)

    loader.load_via_commands_api(valid_rows)
