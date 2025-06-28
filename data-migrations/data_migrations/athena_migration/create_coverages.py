import csv
import arrow

from data_migrations.template_migration.coverage import CoverageLoaderMixin
from data_migrations.utils import (
    fetch_complete_csv_rows,
    fetch_from_json,
    load_fhir_settings,
    reverse_mapping,
)


class CoverageLoader(CoverageLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/coverages.json"
        self.csv_file = "PHI/coverages.csv"
        self.payer_mapping_csv_file = "mappings/insurance_payer_mapping.csv"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.reverse_patient_map = reverse_mapping(self.patient_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.payor_mapping_file = "mappings/payor_mapping.json"
        self.payor_mapping = fetch_from_json(self.payor_mapping_file)
        self.ignore_file = "results/ignored_coverages.csv"
        self.done_file = "results/done_coverages.csv"
        self.error_file = "results/errored_coverages.csv"
        self.validation_error_file = 'results/PHI/errored_coverage_validation.json'
        self.done_records = fetch_complete_csv_rows(self.done_file)

    def make_payer_mapping_file(self):
        data = fetch_from_json(self.json_file)
        payers = []
        for patient_coverages in data:
            for insurance in patient_coverages.get("insurances", []):
                payer_pair = (insurance.get("insurancepackagepayerid", ""), insurance.get("insurancepayername", ""))
                if payer_pair not in payers and f"{payer_pair[0]}|{payer_pair[1]}" not in self.payor_mapping: # uncomment for new ones;
                    payers.append(payer_pair)
        with open(self.payer_mapping_csv_file, "w") as fhandle:
            writer = csv.writer(fhandle, delimiter="\t")
            writer.writerow(("Payer ID", "Payer Name",))
            writer.writerows(payers)

    def make_csv(self):
        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Subscriber",
            "Member ID",
            "Relationship to Subscriber",
            "Coverage Start Date",
            "Payor ID",
            "Order",
            "Group Number",
            "Plan Name",
        ]

        data = fetch_from_json(self.json_file)

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()

            relationship_map = {
                "Self": "self",
                "Child": "child",
                "Spouse": "spouse",
                "Other": "other",
                "Unknown": "other",
            }

            already_seen = []

            for row in data:
                patient_id = row.get("patientdetails", {}).get("enterpriseid", "")
                for coverage in row["insurances"]:
                    coverage_id = coverage["insuranceid"]
                    if coverage_id in already_seen:
                        continue
                    insurance_id_number = coverage.get("insuranceidnumber", "")
                    relationship = relationship_map.get(coverage.get("relationshiptoinsured", ""), "")
                    if relationship != "self" and all(
                        [coverage.get("insurancepolicyholderfirstname"),
                         coverage.get("insurancepolicyholderlastname"),
                         coverage.get("insurancepolicyholderdob"),]
                         ):
                        subscriber_id = self.find_subscriber(
                            coverage["insurancepolicyholderfirstname"],
                            coverage["insurancepolicyholderlastname"],
                            arrow.get(coverage["insurancepolicyholderdob"], "MM/DD/YYYY").date().isoformat(),
                        )
                        if not subscriber_id:
                            subscriber_id = ""
                    elif relationship == "self":
                        subscriber_id = patient_id
                    else:
                        subscriber_id = ""

                    if "issuedate" in coverage:
                        coverage_start_date = arrow.get(coverage["issuedate"], "MM/DD/YYYY").date().isoformat()
                    else:
                        # default if coverage not provided
                        coverage_start_date = "2025-01-01"

                    payor_id = ""
                    if coverage.get("insurancepackagepayerid") or coverage.get("insurancepayername"):
                        payor_key = f'{coverage.get("insurancepackagepayerid", "")}|{coverage.get("insurancepayername", "")}'
                        payor_id = self.payor_mapping.get(payor_key) or f'UNABLE TO MAP {payor_key}'


                    row_to_write = {
                        "ID": coverage_id,
                        "Patient Identifier": patient_id,
                        "Type": "",
                        "Subscriber": subscriber_id,
                        "Member ID": insurance_id_number,
                        "Relationship to Subscriber": relationship_map.get(coverage.get("relationshiptoinsured", ""), ""),
                        "Coverage Start Date": coverage_start_date,
                        "Payor ID": payor_id,
                        "Order": coverage.get("sequencenumber", "1"),
                        "Group Number": "",
                        "Plan Name": coverage["insuranceplanname"],
                    }
                    already_seen.append(coverage_id)
                    writer.writerow(row_to_write)
        print("CSV successfully made")

    def find_missing_rows(self, delimiter=","):
        headers = [
            "ID",
            "Patient Identifier",
            "Type",
            "Subscriber",
            "Member ID",
            "Relationship to Subscriber",
            "Coverage Start Date",
            "Payor ID",
            "Order",
            "Group Number",
            "Plan Name",
        ]

        patient_map = fetch_from_json(self.patient_map_file)

        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)

            with open("PHI/diff_coverages.csv", "w") as new_file:
                writer = csv.DictWriter(new_file, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()

                for row in reader:
                    if row['ID'] in self.done_records:
                        continue
                    if row['Patient Identifier'] not in patient_map:
                        print('No patient to map skipping')
                        continue
                    if not row['Payor ID']:
                        continue
                    if not row["Subscriber"]:
                        row['Subscriber'] = 'UNABLE TO FIND SUBSCRIBER'
                    
                    writer.writerow(row)


if __name__ == "__main__":
    loader = CoverageLoader(environment="phi-test-accomplish")
    #loader.make_payer_mapping_file()
    #loader.make_csv()
    #loader.find_missing_rows()
    valid_rows = loader.validate(delimiter=",")
    loader.load(valid_rows, map_payor=False)
