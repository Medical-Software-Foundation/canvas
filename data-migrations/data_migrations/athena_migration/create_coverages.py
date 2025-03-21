import csv, os

from data_migrations.template_migration.coverage import CoverageLoaderMixin
from data_migrations.utils import fetch_from_json


class CoverageLoader(CoverageLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/coverages.json"
        self.csv_file = "PHI/coverages.csv"
        self.payer_mapping_csv_file = 'mappings/insurance_payer_mapping.csv'

    def make_payer_mapping_file(self):
        data = fetch_from_json(self.json_file)
        payers = []
        for patient_coverages in data:
            for insurance in patient_coverages.get("insurances", []):
                payer_pair = (insurance.get("insurancepackagepayerid", ""), insurance.get("insurancepayername", ""))
                if payer_pair not in payers:
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

            for row in data:
                patient_id = row.get("patientdetails", {}).get("fhir-profile-reference", "").replace("Patient/", "")
                for coverage in row["insurances"]:
                    coverage_id = coverage["insuranceid"]
                    breakpoint()

                    row_to_write = {
                        "ID": coverage_id,
                        "Patient Identifier": patient_id,
                        "Type": "",

                    }


if __name__ == "__main__":
    loader = CoverageLoader(environment="localhost")
    # loader.make_csv()
    loader.make_payer_mapping_file()
