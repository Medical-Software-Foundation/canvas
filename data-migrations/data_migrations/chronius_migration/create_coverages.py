import csv 
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.coverage import CoverageLoaderMixin

class CoverageLoader(CoverageLoaderMixin):
    """
        Load Conditions from Elation to Canvas.

        Elation customer already gave us CSV in desired format, we will 
        then loop through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

        It also produces multiple files:
        - The done_file keeps track of the Avon unique identifier to the canvas
          appointment id and patient key. This helps ensure no duplicate data is transfered and
          helps keep an audit of what was loaded.
        - The error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any data that may need manual fixing and replaying
        - The ignore file keeps track of any records that were skipped over
          during the ingest process potentially due to a patient not being
          in canvas, doctor not being in canvas, etc
        - The validation_error_file keeps track of all the Avon records that failed the validation of
          the Canvas Data Migration Template and why they failed
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'coverages'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.payor_map = fetch_from_json("mappings/payor_map.json")

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)

    def make_csv(self, delimiter=','):
        """
            Fetch the Condition Records from Avon API
            and convert the JSON into a CSV with the columns that match
            the Canvas Data Migration Template
        """
        headers = {
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
            "Plan Name"
        }

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            with open(self.customer_file, 'r') as file:
                reader = csv.DictReader(file, delimiter=delimiter)

                for row in reader:
                    row['ID'] = f'{row["Patient Identifier"]}-{row["Order"]}'

                    if not row["Coverage Start Date"]:
                        row['Coverage Start Date'] = '01/01/2025'

                    if row['Relationship to Subscriber'] == 'self':
                        row['Subscriber'] = row['Patient Identifier']
                    elif subscriber := row['Subscriber']:
                        if subscriber in self.patient_map:
                            row['Subscriber'] = subscriber
                        else:
                            subscriber = self.find_subscriber(name=subscriber)
                            if not subscriber:
                                self.ignore_row(f"{row['ID']}||", "Unable to find subscriber")
                                continue
                            row['Subscriber'] = subscriber

                    writer.writerow(row)

            print("CSV successfully made")


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = CoverageLoader(environment="phi-chronius-test")
    delimiter = ','

    #loader.make_csv(delimiter=delimiter)

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, skip_subscriber_mapping=False)
