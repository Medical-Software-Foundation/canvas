import requests, json, arrow, base64
from customer_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from utils import DrChronoHelper

class AppointmentLoader:
	"""
		DrChrono has an API endpoint for grabbing appointments for a specific patient within a specific date range:
		https://app.drchrono.com/api-docs-old/v4/documentation

		This loader script will loop through the patient map (that has the drchrono patient ID mapped to 
		the canvas patient key), fetch all the patient's appointments within a timeframe, loop through each 
		appointment and calls the FHIR Appointment create endpoint (https://docs.canvasmedical.com/api/appointment/#create) 
		and also the FHIR DocumentReference Create endpoint for a PDF attached to the appointment 
		(https://docs.canvasmedical.com/api/documentreference/#create)
		
		As the script loops through files will keep track of progress: 
		- every appointment that finishes successfully will be a row in the `done_appointments_file`
		  containing the DrChrono Appointment ID, DrChrono Patient ID, Canvas Patient Key, and Canvas Appointment ID.
		  Keeping track of the apts allows nothing to be duplicated when ingesting and keeps an audit of records created in Canvas. 
		- Any appointment that fails will be a row in the `errored_appointments_file` containing the error message. 
		  That way you can go through why they failed and replay or manually fix. 
		- every PDF document that finishes successfully will be a row in the `done_documents_file` 
		  containing the DrChrono Apt ID it is associated with, DrChrono Patient ID,
		  Canvas Patient ID and the Canvas DocumentReference ID. Keeping track of 
		  the finished documents allows nothing to be duplicated when ingesting and keeps an audit of 
		  records created in Canvas. 
		- Any documents that failed will be a row in the `errored_documents_file` containing the 
		  error message. That way you can go through why they failed and replay or manually fix. 
		- Any errored Note State Change Events will be a row in the `errored_note_state_event_file` containing
		  the DrChrono Apt ID, DrChrono Patient ID, Canvas Patient Key and error message. These errors are specifically
		  related to the note not successfully being checked in or locked. These may require manual fixing after.
		- as the patient's finish, they will be a row in the finished_patient_file so that if the script 
		  has to be stopped and replayed, it will skip over patients that finished. 
	"""

	def __init__(self, environment, *args, **kwargs):
		self.patient_map_file = 'PHI_bak/patient_id_map.json'
		self.done_appointments_file = 'results_bak/done_appointments.csv'
		self.errored_appointments_file = 'results_bak/errored_appointments.csv'
		self.done_documents_file = 'results_bak/done_documents.csv'
		self.errored_documents_file = 'results_bak/errored_documents.csv'
		self.ignored_appointments_file = 'results_bak/ignored_appointments.csv'
		self.errored_note_state_event_file = 'results_bak/errored_note_state_events.csv'
		self.finished_patient_file = 'results_bak/finished_patient_appointments.csv'

		self.patient_map = fetch_from_json(self.patient_map_file) 
		self.done_appointments = fetch_complete_csv_rows(self.done_appointments_file)
		self.done_documents = fetch_complete_csv_rows(self.done_documents_file)
		self.doctor_map = fetch_from_json("mappings/doctor_map.json") 
		self.location_map = fetch_from_json("mappings/office_map.json") 
		self.profile_map = fetch_from_json("mappings/profile_map.json") 
		self.finished_patient_ids = fetch_complete_csv_rows(self.finished_patient_file, 'dr_chrono_id')

		self.environment = environment
		self.fumage_helper = load_fhir_settings(self.environment)
		self.drchrono_helper = DrChronoHelper(self.environment)
			   
	def ingest_appointments(self, patient_key, patient_appointments) -> tuple[dict, str]:
		"""
			Loop through a list of drchrono appointments for a specific patient and
			- Ignore appointments that have already been ingested, we want to avoid duplicates
			- Ignore appointments that are not locked or contain the PDF, they were never finished
			  in drchrono and do not need to be moved over for historical purposes
			- See if there is a document of the appointment summary to ingest
			- Map the provider, location, and RFV 
			- Make a FHIR call to create record in Canvas 
			- add the record to the done or errored file to tracking
		"""

		print(f'      Found {len(patient_appointments)} appointments')
		for row in patient_appointments:
			if row['id'] in self.done_appointments:
				print('	Already did apt')
				self.ingest_document(patient_key, row)
				continue

			# we only care about appointments that have a pdf
			# if not row['clinical_note'] or not row['clinical_note'].get('locked'):
			if not row['clinical_note'] or not row['clinical_note'].get('pdf'):
				with open(self.ignored_appointments_file, 'a') as ignored:
					print('	Not locked/has pdf...ignoring')
					ignored.write(f"{row['id']}|{row['patient']}|{patient_key}|{row['status']}|no pdf\n")
				continue

			if row['status'] in ('Cancelled', 'Rescheduled', 'No Show'):
				with open(self.ignored_appointments_file, 'a') as ignored:
					print('	Ignoring due to status')
					ignored.write(f"{row['id']}|{row['patient']}|{patient_key}|{row['status']}|ignored status\n")
				continue

			practitioner_key = self.doctor_map.get(str(row['doctor']))

			if not practitioner_key:
				with open(self.ignored_appointments_file, 'a') as ignored:
					print(f'	Ignoring due no doctor map with {row["doctor"]}')
					ignored.write(f"{row['id']}|{row['patient']}|{patient_key}|{row['status']}|Ignoring due no doctor map with {row['doctor']}\n")
				continue

			# save the clinical pdf as an uncat doc
			self.ingest_document(patient_key, row)
	
			start = arrow.get(row['scheduled_time'])
			location = self.location_map.get(str(row['office']), "75d26374-e449-4f51-872c-f3007be9c451")
			rfv = self.profile_map.get(str(row['profile']), 'No Reason Given')
		
			payload = {
				"resourceType": "Appointment",
				"identifier": [
					{
						"system": "DrChrono",
						"value": row['id'],
					}
				],
				"status": "fulfilled",
				"appointmentType": {
					"coding": [{
							"system": "INTERNAL",
							"code": "drchrono_historical_note",
							"display": "DrChrono Historical Note"
					}]
				},
				"reasonCode":[{
					"text": f"{rfv} - {row['reason']}" if rfv else row['reason']
				}],
				"supportingInformation":[
					{"reference": f"Location/{location}"}
				],
				"start": start.isoformat(),
				"end": start.shift(minutes=int(row['duration'])).isoformat(),
				"participant":[
					{
						"actor": {"reference": f"Patient/{patient_key}"},
						"status": "accepted"
					},
					{
						"actor": {"reference": f"Practitioner/{practitioner_key}"},
						"status": "accepted"
					}
				]
			}
			# print(json.dumps(payload, indent=2))

			try:
				canvas_id = self.fumage_helper.perform_create(payload)
				with open(self.done_appointments_file, 'a') as done:
					print('	Complete Apt')
					done.write(f"{row['id']}|{row['patient']}|{patient_key}|{canvas_id}\n")
			except BaseException as e:            
				e = str(e).replace('\n', '')
				with open(self.errored_appointments_file, 'a') as errored:
					print('	Errored Apt')
					errored.write(f"{row['id']}|{row['patient']}|{patient_key}|{e}\n")
				continue 


			try:				
				# need to check in and lock the appointment
				self.fumage_helper.check_in_and_lock_appointment(canvas_id)
			except BaseException as e:
				e = str(e).replace('\n', '')
				with open(self.errored_note_state_event_file, 'a') as errored_state:
					print('	Errored NSCE')
					errored_state.write(f"{row['id']}|{row['patient']}|{patient_key}|{e}\n")
	
	
	def ingest_document(self, patient_key, document):
		"""
			Try to ingest the Clinical Note PDF document as an uncategorized clinical document, specifically
			a type of an External Medical Record 
			- Ignore documents that have already been ingested
			- Make sure we have a document to ingest
			- Make a FHIR call to create record in Canvas 
			- add the record to the done or errored file to tracking
		"""

		if document['id'] in self.done_documents:
			print('	Already did document')
			return

		pdf = document['clinical_note'].get('pdf')
		if not pdf:
			with open(self.errored_documents_file, 'a') as errored:
				print('	No PDF Found for locked note')
				errored.write(f"{document['id']}|{document['patient']}|{patient_key}|No PDF Found for locked note\n")
			return

		r = requests.get(pdf)
		
		if r.status_code != 200:
			with open(self.errored_documents_file, 'a') as errored:
				print('	Errored document')
				errored.write(f"{document['id']}|{document['patient']}|{patient_key}|{r.text}\n")
			return

		start = arrow.get(document['scheduled_time']).format("YYYY-MM-DD")
		rfv = self.profile_map.get(str(document['profile']), '')
		rfv = f"{rfv} - {document['reason']}" if rfv else document['reason']

		payload = {
			"resourceType": "DocumentReference",
			"extension": [
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
					"valueString": f"From DrChrono imported appointment {rfv} on {start}"
				},
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
					"valueDate": start
				},
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-review-mode",
					"valueCode": "RN"
				},
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-reviewer",
					"valueReference": {
						"reference": "Practitioner/5eede137ecfe4124b8b773040e33be14",
					}
				},
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-priority",
					"valueBoolean": False
				},
				{
					"url": "http://schemas.canvasmedical.com/fhir/document-reference-requires-signature",
					"valueBoolean": False
				}
			],
			"status": "current",
			"type": {
				"coding": [
					{
						"system": "http://loinc.org",
						"code": "11503-0"
					}
				]
			},
			"category": [
				{
					"coding": [
						{
							"system": "http://schemas.canvasmedical.com/fhir/document-reference-category",
							"code": "uncategorizedclinicaldocument"
						}
					]
				}
			],
			"subject": {
				"reference": f"Patient/{patient_key}",
				"type": "Patient"
			},
			"author": [
				{
					"reference": "Practitioner/5eede137ecfe4124b8b773040e33be14",
					"type": "Practitioner"
				}
			],
			"content": [
				{
					"attachment": {
						"contentType": "application/pdf",
						"data": base64.b64encode(r.content).decode('utf-8')
					}
				}
			]
		  }
		
		# print(json.dumps(payload, indent=2))
		try:
			canvas_id = self.fumage_helper.perform_create(payload)
			with open(self.done_documents_file, 'a') as done:
				print('	Complete document')
				done.write(f"{document['id']}|{document['patient']}|{patient_key}|{canvas_id}\n")
		except BaseException as e:
			e = str(e).replace('\n', '')
			with open(self.errored_documents_file, 'a') as errored:
				print('	Errored document')
				errored.write(f"{document['id']}|{document['patient']}|{patient_key}|{e}\n")
	
	def load(self, start_date="1900-01-01", end_date="2024-09-12"):
		"""
			Loop through each patient, skip any patients already finished, 
			make a drchrono api call to grab those patients appointments within a specific time frame,
			(Remember this should only be for historical appointments since they all get created with a specific 
			historical note type) 
			it will also ingest any PDF of the appointments as a Document Reference, 
			and finally add the patient to the finished file. 
		"""
		patient_count = len(self.patient_map)
		for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):
			if drchrono_patient_id in self.finished_patient_ids:
				print(f'Skipping since already done {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
				continue
			
			print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
			patient_appointments = self.drchrono_helper.fetch_drchrono_records("appointments", f'patient={drchrono_patient_id}&verbose=True&date_range={start_date}/{end_date}')
			self.ingest_appointments(canvas_patient_key, patient_appointments)

			with open(self.finished_patient_file, 'a') as patients_finished:
				patients_finished.write(f'{drchrono_patient_id}|{canvas_patient_key}\n')

		print('Done')


	def errored_appointments(self):
		"""
			If you want to replay any failed appointments, this function will loop through the failed ones
			you can find in the self.errored_appointments_file 
		"""

		errored  = [
			# drchrono appointment id, drchrono patient id
			("263963397", "112747920"),
			("199411849", "89033628"),
			("307520706", "111003949"),
			("200866314", "97807383"),
			("215192666", "103739423"),
			("257106270", "111357481"),
			("280107297", "116216763"),
			("268460192", "105253667"),
			("291266967", "105253667"),
			("224404170", "105252171"),
			("240229835", "105252171"),
			("253158098", "105252171"),
			("310031825", "105252171"),
			("311226531", "105252171"),
			("240980565", "108380475"),
			("240986068", "108380475"),
			("253157949", "108380475"),
			("242093286", "108610448"),
		]

		for i, (apt_id, drchrono_patient_id) in enumerate(errored):
			canvas_patient_key = self.patient_map[drchrono_patient_id]
			print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{len(errored)})')

			patient_appointment = self.drchrono_helper.fetch_single_drchrono_record("appointments", apt_id)
			if not self.profile_map.get(str(patient_appointment['profile'])):
				profile = self.drchrono_helper.fetch_single_drchrono_record("appointment_profiles", patient_appointment['profile'])
				if profile.get('id'):
					self.profile_map[str(profile['id'])] = profile['name']

			self.ingest_appointments(canvas_patient_key, [patient_appointment])

		with open("mappings/profile_map.json", 'w', encoding='utf-8') as f:
		    json.dump(self.profile_map, f, ensure_ascii=False, indent=4)

	def errored_nsce(self):
		"""
			Try to replay any errored note state change events that failed to check in or lock the note
		"""

		errored = [
			# appointment externally exposable ids
			"f523b66e-73d6-44c9-b21a-0ef38983d41f",
		]

		for apt_id in errored:
			print(apt_id)
			try:
				self.fumage_helper.check_in_and_lock_appointment(apt_id)
				print('  complete')
			except Exception as e:
				print(e)

	def ingest_appointments_within_time_frame(self, start_date, end_date):
		""" Ingest appointments within a given time frame
			Code ensures no duplicates are created
		"""
		appointments = self.drchrono_header.fetch_drchrono_records("appointments", f"verbose=True&date_range={start_date}/{end_date}")

		appointment_count = len(self.patient_map)
		for i, apt in enumerate(appointments):
			drchrono_patient_id = apt['patient']
			canvas_patient_key = self.patient_map.get(str(drchrono_patient_id))

			if not apt['patient'] or not canvas_patient_key:
				print('No Patient found...ignoring')
				continue

			print(f"Creating Records for apt {apt['id']} - {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{appointment_count})")

			if self.fumage_helper.appointment_already_exists(apt['scheduled_time'], canvas_patient_key):
				# only get the PDF if the appointment already exists
				print('  Appointment already created in Canvas')
				self.ingest_document(canvas_patient_key, apt)
			else:
				self.ingest_appointments(canvas_patient_key, [apt])
		
		print('Done')
if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = AppointmentLoader(environment='customer_identifier')
	loader.load(start_date="1900-01-01", end_date="2024-09-12")

	# If any appointments or note state change events errored, you can replay with this function
	# loader.errored_appointments()
	# loader.errored_nsce()

	# Sometimes a historical data load will ask you to ingest more appointments in a specific time frame
	# use this function and pass the inclusive date range to use
	# loader.ingest_appointments_within_time_frame("2024-09-13", "2024-09-17")