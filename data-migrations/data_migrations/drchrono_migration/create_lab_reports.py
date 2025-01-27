import requests, json, base64
from utils import DrChronoHelper
from customer_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings

class LabResultPDFLoader:
	"""
		DrChrono has multiple API endpoints for grabbing lab results:
		1. The lab order summary endpoint allows filtering by patient: https://app.drchrono.com/api-docs-old/v4/documentation#apidocuments:~:text=Default%20%22NORMAL%22-,/api/lab_orders_summary,-%C2%B6
		   And the payload will contain the `id` of the order to use. 
		2. The lab_results endpoint will allow filtering by the lab order id: 
		   And the payload will contain the `document` ID
		3. Lastly the lab_documents endpoint will allow for fetching of the specific PDF lab document

		This loader script will loop through the patient map (that has the drchrono patient ID mapped to 
		the canvas patient key), fetch all the patient's lab orders, find any lab results associated
		to the lab order and grab the lab document from each result. It will loop through each 
		individual document and call the FHIR DocumentReference Create endpoint (https://docs.canvasmedical.com/api/documentreference/#create)
		
		As the script loops through each files will keep track of progress: 
		- every document that finishes successfully will be a row in the `done_lab_results_file` 
		containing the DrChrono Lab Document ID and the Canvas DocumentReference ID. Keeping track of 
		the finished documents allows nothing to be duplicated when ingesting and keeps an audit of 
		records created in Canvas. 
		- Any documents that failed will be a row in the `errored_lab_results_file` containing the 
		error message. That way you can go through why they failed and replay or manually fix. 
		- as the patient's finish, they will be a row in the finished_patient_file so that if the script 
		has to be stopped and replayed, it will skip over patients that finished. 
	"""


	def __init__(self, environment, *args, **kwargs):
		self.patient_map_file = 'PHI/patient_id_map.json'
		self.done_lab_results_file = 'results/done_lab_results.csv'
		self.errored_lab_results_file = 'results/errored_lab_results.csv'
		self.finished_patient_file = 'results/finished_patient_lab_results.csv'

		self.patient_map = fetch_from_json(self.patient_map_file) 
		self.done_lab_results = fetch_complete_csv_rows(self.done_lab_results_file)
		self.finished_patient_ids = fetch_complete_csv_rows(self.finished_patient_file, 'dr_chrono_id')

		self.environment = environment
		self.fumage_helper = load_fhir_settings(self.environment)
		self.drchrono_helper = DrChronoHelper(self.environment)


	def fetch_drchrono_lab_results_documents(self, lab_orders):
		""" Loop through a patients set of DrChrono lab orders to 
		find any associating lab results in DrChrono. Then create a list
		of all the Lab Documents found
		"""

		document_ids = set()
		for order in lab_orders:
			for result in self.drchrono_helper.fetch_drchrono_records('lab_results', f'order={order["id"]}'):
				document_ids.add(result["document"])
		return document_ids

	def ingest_lab_result_documents(self, canvas_patient_key, drchrono_patient_id, lab_result_document_ids):
		"""
			Loop through a list of drchrono lab documents and
			- Ignore documents that have already been ingested, we want to avoid duplicates
			- Make an DrChrono API call to fetch the single lab document
			- make sure the document is indeed a Lab Result (and not an requisition form)
			- Make sure we have a document contents to ingest
			- Make a FHIR call to create record in Canvas 
			- add the record to the done or errored file to tracking
		"""

		print(f'      Found {len(lab_result_document_ids)} lab results')
		for document_id in lab_result_document_ids:

			if str(document_id) in self.done_lab_results:
				print('      Already did lab result')
				continue

			document = self.drchrono_helper.fetch_single_drchrono_record('lab_documents', document_id)
			if document['type'] != 'RES':
				print('      Document not a lab result...skipping')
				continue

			pdf = document['document']
			if not pdf:
				with open(self.errored_lab_results_file, 'a') as errored:
					print('      No PDF Found for lab result')
					errored.write(f"{document['id']}|{drchrono_patient_id}|{canvas_patient_key}|No PDF Found for lab result\n")
				return

			r = requests.get(pdf)
			
			if r.status_code != 200:
				with open(self.errored_lab_results_file, 'a') as errored:
					print('      Errored document')
					errored.write(f"{document['id']}|{drchrono_patient_id}|{canvas_patient_key}|{r.text}\n")
				return

			payload = {
			    "resourceType": "Parameters",
			    "parameter": [
			        {
			            "name": "labReport",
			            "resource": {
			                "resourceType": "DiagnosticReport",
			                "status": "final",
			                "category": [
			                    {
			                        "coding": [
			                            {
			                                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
			                                "code": "LAB",
			                                "display": "Laboratory"
			                            }
			                        ]
			                    }
			                ],
			                "subject": {
			                    "reference": f"Patient/{canvas_patient_key}",
			                    "type": "Patient"
			                },
			                "presentedForm": [
			                    {
			                        "data": base64.b64encode(r.content).decode('utf-8'),
			                        "contentType": "application/pdf"
			                    }
			                ],
			                "effectiveDateTime": document['timestamp'],
			                "code": {
			                    "coding": []
			                }
			            }
			        }
			    ]
			}

			# print(json.dumps(payload, indent=2))

			try:
				canvas_id = self.fumage_helper.perform_create(payload)
				with open(self.done_lab_results_file, 'a') as done:
					print('	Complete Lab Result')
					done.write(f"{document['id']},{drchrono_patient_id},{canvas_patient_key},{canvas_id}\n")
			except BaseException as e:            
				e = str(e).replace('\n', '')
				with open(self.errored_lab_results_file, 'a') as errored:
					print('	Errored Lab Result')
					errored.write(f"{document['id']}|{drchrono_patient_id}|{canvas_patient_key}|{e}\n")
				continue 


	def load(self):
		"""
			Loop through each patient, skip any patients already finished, 
			make a drchrono api call to grab those patients lab orders,
			if any lab orders are found, make another api call to get the 
			lab_results associated with the order to see if any have a PDF
			then ingest the PDF documents using Canvas FHIR endpoints, 
			and finally add the patient to the finished file. 
		"""

		patient_count = len(self.patient_map)
		for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):
			if drchrono_patient_id in self.finished_patient_ids:
				print(f'Skipping since already done {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
				continue
			
			print(f'Creating Lab Reports for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')
			lab_orders = self.drchrono_helper.fetch_drchrono_records("lab_orders_summary", f"patient={drchrono_patient_id}")
			if lab_orders:
				print(f'      Found {len(lab_orders)} orders')
				lab_result_document_ids = self.fetch_drchrono_lab_results_documents(lab_orders)
				self.ingest_lab_result_documents(canvas_patient_key, drchrono_patient_id, lab_result_document_ids)
			else:
				print(f'      Zero lab orders found for patient')

			with open(self.finished_patient_file, 'a') as patients_finished:
				patients_finished.write(f'{drchrono_patient_id},{canvas_patient_key}\n')


		print('Done')

	def reload_errored_lab_results(self):
		"""
			After the load is complete, go through the errored file
			and pull out the rows that you need replayed. 
		"""
		errored = [
			# drchrono lab document id|drchrono patient id|canvas patient key
			"13459655|111742355|8c5ea318e2f44c0c8a350c73daf9ab4c",
			"14164448|87225980|6eac76f6339647bc88d1c91af6e51ed2",
			"8209095|89336202|f6764c0712e04a4a845f7864fcb23ac1",
			"11131114|96267021|fa1cc3fcd4a142cb9b5e7714370eb0a6",
			"9868736|101876612|6d87e372fce44682bcd1df5b93e891a5",
		]

		for e in errored:
			doc_id, drchrono_patient_id, canvas_patient_key = e.split('|')
			print(f'Creating Lab Reports for {drchrono_patient_id}/{canvas_patient_key}')

			self.ingest_lab_result_documents(canvas_patient_key, drchrono_patient_id, [doc_id])


if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = LabResultPDFLoader(environment='customer_identifier')
	loader.load()
	#loader.reload_errored_lab_results()

""" 
Will need to manually mark these as review not required since that can't be controlled via API
An engineer that can ssh into the instance will need to run this
"""

# count = 0
# labs = LabReport.objects.filter(review_mode='RR')
# print(labs.count())
# for l in labs:
#     if l.name == 'Lab':
#         count += 1
#         print(count)
#         l.review_mode = 'RN'
#         l.save()
# print(count)
