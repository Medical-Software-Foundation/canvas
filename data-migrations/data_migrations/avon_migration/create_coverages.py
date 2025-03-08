import csv
import os

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.template_migration.coverage import CoverageLoaderMixin
from data_migrations.utils import fetch_complete_csv_rows, fetch_from_json, reverse_mapping
from data_migrations.utils import load_fhir_settings


class CoverageLoader(CoverageLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.json_file = "PHI/coverages.json"
        self.csv_file = "PHI/coverages.csv"
        self.ignore_file = "results/ignored_coverages.csv"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.reverse_patient_map = reverse_mapping(self.patient_map_file)
        self.done_file = 'results/done_coverages.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = 'results/errored_coverages.csv'
        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)
        self.fumage_helper = load_fhir_settings(environment)
        self.payor_mapping_file = "mappings/payor_mapping.json"
        self.payor_mapping = fetch_from_json(self.payor_mapping_file)

        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.validation_error_file = 'results/PHI/errored_coverage_validation.json'

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Data Migration"
        super().__init__(*args, **kwargs)


    def make_csv(self, delimiter='|') -> None:
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/insurance_policies", self.json_file, param_string='')

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

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:
                subscriber = ""
                subscriber_relationship = row["policyholder"]["patient_relationship_to_policyholder"]
                if subscriber_relationship == "self":
                    subscriber = row["patient"]
                else:
                    subscriber_first_name = row["policyholder"]["first_name"]
                    subscriber_last_name = row["policyholder"]["last_name"]
                    subscriber_dob = row["policyholder"]["date_of_birth"]
                    # All criteria must be present to do a patient search
                    if all([
                        subscriber_first_name,
                        subscriber_last_name,
                        subscriber_dob
                    ]):
                        subscriber = self.find_subscriber(
                            subscriber_first_name,
                            subscriber_last_name,
                            subscriber_dob
                        ) or ""

                if subscriber_relationship not in ['child', 'spouse', 'self', 'injured', 'other']:
                    subscriber_relationship = 'other'

                coverage_order_map = {
                    'primary': '1',
                    'secondary': '2',
                    'tertiary': '3'
                }
                coverage_order = coverage_order_map.get(row['type'], "")

                row_to_write = {
                    "ID": row["id"],
                    "Patient Identifier": row["patient"],
                    "Type": "",
                    "Subscriber": subscriber,
                    "Member ID": row["insurance_card"]["member_id"],
                    "Relationship to Subscriber": subscriber_relationship,
                    "Coverage Start Date": "2025-03-03",
                    "Payor ID": self.payor_mapping.get(f'{row["insurance_card"]["payer_id"]}|{row["insurance_card"]["payer_name"]}', ""),
                    "Order": coverage_order,
                    "Group Number": row["insurance_card"]["group_number"] or "",
                    "Plan Name": row["insurance_card"]["plan_name"] or ""
                }

                if not row_to_write["Payor ID"]:
                    self.ignore_row(row["id"], f'Ignoring due to no payor mapping for {row["insurance_card"]["payer_id"]}|{row["insurance_card"]["payer_name"]}')
                    continue

                writer.writerow(row_to_write)

            print("CSV successfully made")


if __name__ == "__main__":
    # change the customer_identifier to what is defined in your config.ini file
    loader = CoverageLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter=delimiter)
    #loader.load(valid_rows, map_payor=False)
