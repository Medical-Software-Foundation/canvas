import requests, json, base64
from utils import DrChronoHelper
from customer_migrations.utils import load_fhir_settings, fetch_from_json, fetch_complete_csv_rows

class DocumentLoader:
	"""
		DrChrono has an API endpoint for grabbing documents for a specific patient:
		https://app.drchrono.com/api-docs-old/v4/documentation#apidocuments:~:text=suspended%20or%20not-,/api/documents,-%C2%B6

		This loader script will loop through the patient map (that has the drchrono patient ID mapped to 
		the canvas patient key), fetch all the patient's documents, loop through each 
		individual document and call the FHIR DocumentReference Create endpoint (https://docs.canvasmedical.com/api/documentreference/#create)
		
		As the script loops through files will keep track of progress: 
		- every document that finishes successfully will be a row in the `done_documents_file` 
		containing the DrChrono Document ID and the Canvas DocumentReference ID. Keeping track of 
		the finished documents allows nothing to be duplicated when ingesting and keeps an audit of 
		records created in Canvas. 
		- Any documents that failed will be a row in the `errored_documents_file` containing the 
		error message. That way you can go through why they failed and replay or manually fix. 
		NOTE: a lot of the DrChrono documents will error because they are not PDF documents, 
		Canvas only accepts PDFs. There was a decision when this script was built to ignore non PDFs. 
		But if that does not work for your use case, you will need code to help covert images to PDFs. 
		- as the patient's finish, they will be a row in the finished_patient_file so that if the script 
		has to be stopped and replayed, it will skip over patients that finished. 
	"""

	def __init__(self, environment, *args, **kwargs):
		self.patient_map_file = 'PHI/patient_id_map.json'
		self.done_documents_file = 'results/done_uncat_documents.csv'
		self.errored_documents_file = 'results/errored_uncat_documents.csv'
		self.finished_patient_file = 'results/finished_patient_uncat_documents.csv'

		self.patient_map = fetch_from_json(self.patient_map_file) 
		self.done_documents = fetch_complete_csv_rows(self.done_documents_file)
		self.finished_patient_ids = fetch_complete_csv_rows(self.finished_patient_file, 'dr_chrono_id')

		self.environment = environment
		self.fumage_helper = load_fhir_settings(self.environment)
		self.drchrono_header = DrChronoHelper(self.environment)
		

	def ingest_documents(self, patient_key, documents):
		"""
			Loop through a list of drchrono documents and
			- Ignore documents that have already been ingested, we want to avoid duplicates
			- Make sure we have a document to ingest
			- Make a FHIR call to create record in Canvas 
			- add the record to the done or errored file to tracking
		"""

		print(f'      Found {len(documents)} documents')
		for document in documents:

			if document['id'] in self.done_documents:
				print('	Already did document')
				return

			pdf = document['document']
			if not pdf:
				with open(self.errored_documents_file, 'a') as errored:
					print('      No document found')
					errored.write(f"{document['id']}|{document['patient']}|{patient_key}|No document found\n")
				return

			r = requests.get(pdf)
			
			if r.status_code != 200:
				with open(self.errored_documents_file, 'a') as errored:
					print('      Errored document')
					errored.write(f"{document['id']}|{document['patient']}|{patient_key}|{r.text}\n")
				return

			payload = {
				"resourceType": "DocumentReference",
				"extension": [
					{
						"url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
						"valueString": f"DrChrono imported: {document['description']}"
					},
					{
						"url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
						"valueDate": document['date']
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
							"code": "34109-9"
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
					print('      Complete document')
					done.write(f"{document['id']}|{document['patient']}|{patient_key}|{document['description']}|{canvas_id}\n")
			except BaseException as e:
				e = str(e).replace('\n', '')
				with open(self.errored_documents_file, 'a') as errored:
					print('      Errored document')
					errored.write(f"{document['id']}|{document['patient']}|{patient_key}|{document['description']}|{e}\n")
		
	def load(self):
		"""
			Loop through each patient, skip any patients already finished, 
			make a drchrono api call to grab those patients documents, 
			then ingest their documents using Canvas FHIR endpoints, 
			and finally add the patient to the finished file. 
		"""

		patient_count = len(self.patient_map)
		for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):
			if drchrono_patient_id in self.finished_patient_ids:
				print(f'Skipping since already done {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
				continue
			
			print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
			patient_documents = self.drchrono_header.fetch_drchrono_records("documents", f"patient={drchrono_patient_id}")
			self.ingest_documents(canvas_patient_key, patient_documents)

			with open(self.finished_patient_file, 'a') as patients_finished:
				patients_finished.write(f'{drchrono_patient_id}|{canvas_patient_key}\n')

		print('Done')


	def reload_errored_docs(self):
		"""
			After the load is complete, go through the errored_documents_file
			and pull out the rows that you need replayed. 
		"""

		errored = [
			# (drchrono_document_id, drchrono_patient_id, canvas_patient_key )
			("264315572", "90231521", "ba1bcded7f8e4d2cb56d24c2d22a2214"),
			("319930187", "121151013", "4534783c124c4e86be256901f5e0648c"),
			("293874450", "116943566", "b4f8c966ae04401f87092e51bb5867ad"),
			("288576560", "109439359", "35f81b77143c448db83d87ba4d410ae9"),
			("292152604", "109439359", "35f81b77143c448db83d87ba4d410ae9"),
			("188546244", "92571461", "cf31ef38965f4658a492dbf838d2fb7d"),
			("181583025", "89371768", "59cb6044bfc14ad1a9e700b9a5de18f0")
		]

		for (_id, drchrono_patient_id, canvas_patient_key) in errored:
			print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key}')
			
			# fetch the Drchrono record using the Drchrono document id
			patient_documents = self.drchrono_header.fetch_single_drchrono_record("documents", _id)
			self.ingest_documents(canvas_patient_key, [patient_documents])


if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = DocumentLoader(environment='customer_identifier')
	#loader.load()
	# loader.reload_errored_docs()