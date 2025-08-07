import csv
from data_migrations.utils import (
    fetch_from_json,
    fetch_complete_csv_rows,
    load_fhir_settings
)
from data_migrations.template_migration.immunization import ImmunizationMixin


class ImmunizationLoader(ImmunizationMixin):
    def __init__(self, environment, *args, **kwargs) -> None:
        self.data_type = 'immunizations'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.allergy_map_file = "mappings/allergy_coding_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map = fetch_from_json(self.note_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        # default needed for mapping
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Chronius Data Migration"
        super().__init__(*args, **kwargs)

    def make_csv(self, delimiter):
        headers = [
            "ID",
            "Patient Identifier",
            "Date Performed",
            "Immunization Text",
            "CVX Code",
            "Comment",
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)

                for row in reader:
                    customer_name = row.pop('Name')
                    date = row.pop("Occurrence Date/Time")
                    row['ID'] = f'{row["Patient Identifier"]}-{customer_name}-{date}'

                    row['Immunization Text'] = customer_name
                    row['Date Performed'] = date

                    row.pop('CPT Code')
                    writer.writerow(row)

            print("CSV successfully made")


if __name__ == "__main__":
    loader = ImmunizationLoader(environment="phi-chronius-test")
    delimiter = ','
    #loader.make_csv(delimiter)
    valid_rows = loader.validate()
    loader.load(valid_rows)
