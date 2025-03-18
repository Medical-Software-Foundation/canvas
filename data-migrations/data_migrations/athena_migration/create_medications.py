import csv, os

from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.utils import fetch_from_json, write_to_json, load_fhir_settings, fetch_complete_csv_rows


class MedicationLoader(MedicationLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/medications.json"
        self.csv_file = 'PHI/medications.csv'
        # self.fumage_helper = load_fhir_settings(environment)

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
    loader = MedicationLoader(environment="localhost")
    loader.make_csv()
