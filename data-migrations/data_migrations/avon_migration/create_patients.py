import requests, json, base64
from customer_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from customer_migrations.template_migrations.patient import PatientLoaderMixin
from utils import AvonHelper

class PatientLoader(PatientLoaderMixin):
	"""

	"""


	def __init__(self, environment, *args, **kwargs):
		self.patient_map_file = 'PHI/patient_id_map.json'
		self.environment = environment
		self.fumage_helper = load_fhir_settings(self.environment)
		self.avon_helper = AvonHelper(environment)


if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = PatientLoader(environment='phi-collaborative-test')
	print(self.avon_helper.__dict__)

