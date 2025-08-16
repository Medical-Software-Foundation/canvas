from data_migrations.utils import fetch_from_json, load_fhir_settings
from data_migrations.template_migration.utils import FileWriterMixin
from data_migrations.template_migration.note import NoteMixin

class UpdateNotes(NoteMixin, FileWriterMixin):

	def __init__(self, environment, *args, **kwargs):
		self.environment = environment
		self.note_map_file = "mappings/historical_note_map.json"
		self.note_map = fetch_from_json(self.note_map_file)
		self.fumage_helper = load_fhir_settings(self.environment)
		self.error_file = "results/errored_nsce.csv"
		super().__init__(*args, **kwargs)


	def update_notes(self, state):

		total = len(self.note_map)
		for i, (patient_key, note_id) in enumerate(self.note_map.items()):
			try:
				self.perform_note_state_change(note_id, state)
				print(f'Updated note {note_id} on {patient_key} ({i+1}/{total})')
			except Exception as e:
				self.error_row(f"{note_id}||{patient_key}", e)


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = UpdateNotes(environment="phi-iconhealth-test")
    loader.update_notes(state='LKD')