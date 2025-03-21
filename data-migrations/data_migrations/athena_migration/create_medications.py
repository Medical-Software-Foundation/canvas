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
                    medication_id = medication.get("id", "")
                    patient_id = medication.get("subject", {}).get("reference", "").replace("Patient/", "")
                    status = medication.get("status", "")
                    if status == "cancelled":
                        status = "entered-in-error"
                    if status == "completed":
                        status = "stopped"
                    if status == "draft": # how should we map this?
                        status = ""

                    row_to_write = {
                        "ID": medication_id,
                        "Patient Identifier": patient_id,
                        "Status": status,
                        "RxNorm/FDB Code": "", # not in file
                        "SIG": medication["dosageInstruction"][0].get("text", "") if medication.get("dosageInstruction") else "",
                        "Medication Name": medication.get("medicationReference", {}).get("display", ""),
                        "Original Code": "",
                    }

                    writer.writerow(row_to_write)

        print("CSV successfully made")

if __name__ == "__main__":
    loader = MedicationLoader(environment="phi-test-accomplish")
    # loader.make_csv()
    # loader.make_fdb_mapping()
    loader.map()
