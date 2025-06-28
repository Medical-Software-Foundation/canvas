import csv
from data_migrations.utils import (
    fetch_from_json,
    fetch_complete_csv_rows,
    load_fhir_settings
)
from data_migrations.template_migration.immunization import ImmunizationMixin


class ImmunizationLoader(ImmunizationMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.json_file = "PHI/immunizations.json"
        self.csv_file = "PHI/immunizations.csv"
        self.fumage_helper = load_fhir_settings(environment)
        self.ignore_file = "results/ignored_immunizations.csv"
        self.error_file = "results/errored_immunizations.csv"
        self.done_file = "results/done_immunizations.csv"
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.validation_error_file = 'results/PHI/errored_immunization_validation.json'

        self.default_location = "7d1e74f5-e3f4-467d-81bb-08d90d1a158a"
        self.default_note_type_name = "Athena Historical Note"
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Date Performed",
            "Immunization Text",
            "CVX Code",
            "Comment",
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            for row in data:
                for immunization in row["immunizations"]:
                    if immunization.get("resourceType") == "Provenance":
                        self.ignore_row(immunization["id"], "Provenance record - ignoring")
                        continue
                    if immunization.get("status") != "completed":
                        self.ignore_row(immunization["id"], "Immunization status is not 'completed'")
                        continue
                    cvx_codes = [c for c in immunization.get("vaccineCode", {}).get("coding", []) if c["system"] == "http://hl7.org/fhir/sid/cvx"]
                    immunization_text = cvx_codes[0]["display"]
                    cvx_code = cvx_codes[0]["code"]
                    writer.writerow({
                        "ID": immunization["id"],
                        "Patient Identifier": immunization["patient"]["reference"].split("-")[-1],
                        "Date Performed": immunization["occurrenceDateTime"],
                        "Immunization Text": immunization_text,
                        "CVX Code": cvx_code,
                        "Comment": ""
                    })


if __name__ == "__main__":
    loader = ImmunizationLoader(environment="phi-test-accomplish")
    # loader.make_csv()
    valid_rows = loader.validate()
    loader.load(valid_rows)
