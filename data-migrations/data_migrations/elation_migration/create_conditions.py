import csv, os

from data_migrations.template_migration.condition import ConditionLoaderMixin
from data_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows

class ConditionLoader(ConditionLoaderMixin):
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
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = "PHI/conditions.json"
        self.csv_file = 'PHI/conditions.csv'
        self.ignore_file = 'results/ignored_conditions.csv'
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.validation_error_file = 'results/PHI/errored_condition_validation.json'
        self.error_file = 'results/errored_conditions.csv'
        self.done_file = 'results/done_conditions.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.note_map_file = "mappings/historical_note_map.json"
        self.note_map = fetch_from_json(self.note_map_file)

        # default needed for mapping
        self.default_location = "c403e466-0147-4ece-8f70-f1caecd55ec6"
        self.default_note_type_name = "Icon Historical Note"
        super().__init__(*args, **kwargs)


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = ConditionLoader(environment='phi-iconhealth-test')
    delimiter = ','

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # # If you are ready to load the rows that have passed validation to your Canvas instance
    #loader.load(valid_rows)
