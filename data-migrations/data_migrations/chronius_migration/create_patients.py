from data_migrations.utils import load_fhir_settings
from data_migrations.template_migration.patient import PatientLoaderMixin

class PatientLoader(PatientLoaderMixin):
    """
        Load Patients Canvas.

        Firstloops through the CSV to validate the columns according to Canvas Data Migration Template
        and lastly loads the validated rows into Canvas via FHIR

        It also produces multiple files:
        - The patient_map_file keeps track of the Avon unique identifier to the canvas patient key.
          This allows for all other data types for data migration to be linked to the correct patient
        - The patient_error_file keeps track of any errors that happen during FHIR ingestion and keeps
          track of any patients that may need manual fixing and replaying
        - The validation_error_file keeps track of all the Avon patients that failed the validation of
          the Canvas Data Migration Template and why they failed
    """


    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.csv_file = 'PHI/patients.csv'
        self.json_file = 'PHI/patients.json'
        self.validation_error_file = 'PHI/errored_patient_validation.json'
        self.error_file = 'results/PHI/errored_patients.csv'
        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = PatientLoader(environment='chronius')
    delimiter = ','

    # Validate the CSV values with the Canvas template data migration rules
    valid_rows = loader.validate(delimiter=delimiter)

    # If you are ready to load the rows that have passed validation to your Canvas instance
    loader.load(valid_rows, system_unique_identifier='chroniuscare', require_identifier=True)

    #loader.fumage_helper.build_patient_external_identifier_map("chroniuscare", "PHI/patient_id_map.json")