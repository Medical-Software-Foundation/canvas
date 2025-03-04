import arrow

from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from data_migrations.template_migration.allergy import AllergyLoaderMixin

class AllergyLoader(AllergyLoaderMixin):
    """
        Load Allergies from Elation to Canvas.

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
        self.data_type = 'allergies'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.note_map = fetch_from_json(self.note_map_file)
        self.payor_map = fetch_from_json("mappings/payor_map.json")
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")

        # default needed for mapping
        self.default_location = "afad4e70-ca25-4a32-9f5c-2c83e2877b43"
        self.default_note_type_name = "Icon Data Migration"
        super().__init__(*args, **kwargs)

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = AllergyLoader(environment="phi-iconhealth-test")
    delimiter = ','

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, {"encounter_start_time": "2025-01-31"})
