import csv, json

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import (
    fetch_from_json,
    write_to_json,
    load_fhir_settings,
    fetch_from_csv,
    fetch_complete_csv_rows
)
from data_migrations.template_migration.utils import validate_date
from data_migrations.template_migration.consent import ConsentLoaderMixin

class ConsentLoader(ConsentLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'consents'
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f"PHI/{self.data_type}.csv"
        self.ignore_file = f"results/ignored_{self.data_type}.csv"
        self.done_file = f'results/done_{self.data_type}.csv'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
        self.fumage_helper = load_fhir_settings(environment=environment)
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map = fetch_from_json(self.patient_map_file) 

    def make_csv(self, delimiter="|"):
        data = self.avon_helper.fetch_records(f"v2/form_responses", self.json_file, param_string='')

        headers = [
            "ID",
            "Patient Identifier",
            "Status",
            "Code",
            "Date"
        ]

        consent_coding_mapping = {
            "Consent for Telemedicine, Use of PHI and Privacy Practices": "consent_telemedicine",
            "Release of Medical Information: Patient/Representative Signature": "release_medical_information"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            #types {'incoming', 'template', 'pdf', 'image'}
            for row in data:
                for section in row['sections']:

                    for answer in section['answers']:
                        if answer['type'] != 'consent':
                            self.ignore_row(answer["id"], f"Form Answer is for {answer['name']}")
                            continue

                        if answer['e_sign_consent_given'] is None:
                            self.ignore_row(answer["id"], f"Consent answer is null")
                            continue

                        csv_row = {
                            "ID": answer['id'],
                            "Patient Identifier": answer['patient'],
                            "Status": "active" if answer['e_sign_consent_given'] else "rejected",
                            "Code": consent_coding_mapping.get(answer['name']),
                            "Date": answer['date'][:10] if answer['date'] else row['last_updated_at'][:10]
                        }

                        writer.writerow(csv_row)

        print("Successfully made CSV")


if __name__ == "__main__":
    loader = ConsentLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter=delimiter)
    loader.load(valid_rows)
