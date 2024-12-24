import requests, json, csv, base64, io, os
from utils import DrChronoHelper
from customer_migrations.utils import fetch_from_csv, fetch_from_json, fetch_complete_csv_rows, load_fhir_settings
from PIL import Image

class CoverageLoader:
    """
        DrChrono API shows the primary, secondary, and tertiary insurance of patients in the 
        api/patients endpoint with the verbose=True parameter

        This loader script will loop through the patient map (that has the drchrono patient ID mapped to 
        the canvas patient key), fetch all the patient's coverages. It will loop through each 
        individual coverage and call the FHIR Coverage Create endpoint and if the coverage has images of 
        insurance card it will call the FHIR DocumentReference Create endpoint 
        
        As the script loops through each files will keep track of progress: 
        - every coverage that finishes successfully will be a row in the `done_coverages_file` 
        containing the DrChrono Patient ID/coverage rank and the Canvas Coverage ID. Keeping track of 
        the finished coverages allows nothing to be duplicated when ingesting and keeps an audit of 
        records created in Canvas. 
        - Any coverages that failed will be in a row in the `errored_coverages_file` containing the 
        error message. That way you can go through why they failed and replay or manually fix. 
        - every insurance card images that successfully is ingested will be a row in the `done_documents_file` 
        containing the DrChrono Coverage ID/rank and the Canvas DocumentReference ID. Keeping track of 
        the finished documents allows nothing to be duplicated when ingesting and keeps an audit of 
        records created in Canvas. 
        - Any insurance cards that failed will be a row in the `errored_documents_file` containing the 
        error message. That way you can go through why they failed and replay or manually fix. 
    """

    def __init__(self, environment, *args, **kwargs):
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_file = 'PHI/patients.csv'
        self.coverages_file = 'PHI/coverages.csv'
        self.done_coverages_file = 'results/done_coverages.csv'
        self.errored_coverages_file = 'results/errored_coverages.csv'
        self.done_documents_file = 'results/done_insurance_cards.csv'
        self.errored_documents_file = 'results/errored_insurance_cards.csv'
        self.payer_mapping_csv_file = 'mappings/insurance_payer_mapping.csv'
        self.ignored_coverages_file = 'results/ignored_coverages.csv'

        # DrChrono does not have a coverage start date in their APIs so we will add all coverages
        # with a specific start date. We chose the day this customer went live on Canvas
        self.start_date = "2024-09-13"

        self.ignored_coverages = fetch_complete_csv_rows(self.ignored_coverages_file, delimiter='|')
        self.done_documents = fetch_complete_csv_rows(self.done_documents_file, delimiter='|',key=['id', 'rank', 'image'])
        self.patient_map = fetch_from_json(self.patient_map_file) 
        self.done_coverages = fetch_complete_csv_rows(self.done_coverages_file)
        self.payer_map = get_payer_mapping_file()
        self.drchrono_records = {}

        self.environment = environment
        self.fumage_helper = load_fhir_settings(self.environment)
        self.drchrono_helper = DrChronoHelper(self.environment)

    def fetch_coverage_information(self, filename=None, files=None, key='id', delimiter='|'):
        """
            DrChrono does not have a coverage endpoint directly, so to grab this information
            you can use the patients endpoint with a verbose=True parameter. This will give you the 
            primary_insurance, secondary_insurance, tertiary_insurance fields. 

            This function's goal is to grab/create a CSV of the coverage specific information
            for the patient's we are ingesting data for. Since we will output the results to 
            a CSV, we first check to see if that CSV is already made and return it. That will 
            guarentee we are only using the API for the first initial data grab. 
        """

        filename = filename or self.coverages_file
        if os.path.isfile(filename):
            return fetch_from_csv(filename, key, delimiter)

        if not os.path.isfile(self.patient_file):
            fetch_drchrono_records_from_file('patients', filename=self.patient_file, param_string='verbose=True', key='id')
        
        fields_we_care_about = ["patient_key", "id", "chart_id", "first_name", "middle_name", "last_name", "date_of_birth", "social_security_number", "primary_insurance", "secondary_insurance", "tertiary_insurance"]
        with open(filename, 'w') as coverage_file:
            writer = csv.DictWriter(coverage_file, fieldnames=fields_we_care_about, delimiter=delimiter)
            writer.writeheader()
            for file in (files or [self.patient_file]):
                with open(file, 'r') as patient_file:
                    reader = csv.DictReader(patient_file)
                    for row in reader:
                        if row['id'] in patient_map:
                            new_row = {k: v for k, v in row.items() if k in fields_we_care_about}
                            for insurance in ("primary_insurance", "secondary_insurance", "tertiary_insurance"):
                                if not eval(new_row[insurance])['insurance_company']:
                                    new_row[insurance] = ""
                            new_row['patient_key'] = patient_map[row['id']]
                            writer.writerow(new_row)

        self.coverages = fetch_from_csv(filename, key, delimiter)

    def get_payer_mapping_file(self, delimiter='|'): 
        """
            Generate a dict of the drchrono insurance to the canvas organization payer
        """

        filename = self.payer_mapping_csv_file
        if os.path.isfile(filename):
            with open(filename, 'r') as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                return {f"{row['insurance_company']}|{row['insurance_payer_id']}": row['canvas_payer_id'] for row in reader}


    def make_payer_mapping_file(self, delimiter='|'):
        """
            This function will output to a file all the unique insurance company and payers found
            for the patients in drchrono. 

            After the file is exported, there will be manual mapping required to find the 
            Canvas FHIR OrganizationalEntity to map to for each insurance
        """

        payers = set()
        with open(self.coverages_file, 'r') as coverage_file:
            reader = csv.DictReader(coverage_file, delimiter=delimiter)
            for row in reader:
                for insurance in ("primary_insurance", "secondary_insurance", "tertiary_insurance"):
                    if found_insurance := row[insurance]:
                        i = eval(found_insurance)
                        payers.add((i['insurance_company'],i['insurance_payer_id']))
        
        with open(filename, 'w') as mapping_file:
            mapping_file.write('insurance_company|insurance_payer_id|canvas_payer_id\n')
            for insurance_company,insurance_payer_id in payers:
                mapping_file.write(f'{insurance_company}|{insurance_payer_id}|\n')


    def find_subscriber(self, row, patient_key):
        """
            This function will return the canvas patient key of the coverage's subscriber. 
            If the coverage's subscriber is the same as the patient the coverage is for, then we can 
            return the patient key

            If the subscriber is a different patient, DrChrono only gives us demographics about the 
            subscriber, so we must perform a FHIR Patient Search to find a matching patient
            based on last name, first name, and DOB
        """

        if row['is_subscriber_the_patient'] or not row['subscriber_first_name']:
            return patient_key
        
        search_parameters = {
            'family': row['subscriber_last_name'],
            'given': row['subscriber_first_name']
        }

        if dob :=  row['subscriber_date_of_birth']:
            search_parameters["birthdate"] = dob

        response = self.fumage_helper.search('Patient', search_parameters)

        if response.status_code != 200:
            raise Exception(f"Failed to find subscriber with {response.url} and error {response.text}")

        data = response.json().get('entry', [])
        if len(data) == 1:
            return data[0]['resource']['id']

        return patient_key
    
    def ingest_coverages(self, patient_key, patient_coverages) -> tuple[dict, str]:
        """
            Loop through a drchrono's patient list of coverages. Each patient could have 
            a primary, secondary, or tertiary coverage to ingest. 

            We will skip over any coverages that are already ingested or determined to ignore

            Here is the fields for each coverage type from drchrono:

                "insurance_company": "Cigna",
                "insurance_id_number": "U7126776904",
                "insurance_group_name": "",
                "insurance_group_number": "",
                "insurance_claim_office_number": "",
                "insurance_payer_id": "62308",
                "insurance_plan_name": "",
                "insurance_plan_type": "12",
                "is_subscriber_the_patient": True,
                "patient_relationship_to_subscriber": "",
                "subscriber_first_name": "",
                "subscriber_middle_name": "",
                "subscriber_last_name": "",
                "subscriber_suffix": "",
                "subscriber_date_of_birth": None,
                "subscriber_social_security": "",
                "subscriber_gender": "",
                "subscriber_address": "",
                "subscriber_city": "",
                "subscriber_zip_code": "",
                "subscriber_state": "",
                "subscriber_country": "US",
                "photo_front": "https://drchrono-uploaded-media-production.s3.amazonaws.com/clinical/2022/06/Cigna_U7126776904_703b2fda-9a80-4f35-ab11-5f59fc29ff1a.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=3600&X-Amz-Credential=redacted%2F20240926%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-SignedHeaders=host&X-Amz-Date=20240926T162918Z&X-Amz-Signature=6e7c57ab279c2086f38ba8dff5a60f37f787ade389404792681aa1e3a5ca6fdb",
                "photo_back":
        """
        for row in patient_coverages:
            for insurance in ("primary_insurance", "secondary_insurance", "tertiary_insurance"):
                key = f"{row['id']}|{insurance}"
                if key in self.ignored_coverages:
                    print('   Already determined to ignore')
                    continue
                    
                if found_insurance := row[insurance]:
                    print(f'   Found {insurance}')
                    self.ingest_specific_coverage(row['id'], patient_key, insurance, eval(found_insurance))

    def ingest_specific_coverage(self, _id, patient_key, rank, row):
        """
            Ingest one coverage record via FHIR Coverage endpoint and any insurance cards via FHIR DocumentReference. 

            The function will follow this logic: 
                1. Ensure there is a payer to map to in Canvas. If there is no payer mapping, export to the ignored_coverages_file to deal with later
                2. Ingest any insurance cards as a DocumentReference
                3. Skip over any coverages already finished to avoid duplications in the chance that the script was replayed
                4. Try to find the subscriber of the coverage's canvas patient key.
                5. Define any mappings 
                6. Create coverage
            If any step fails, the row will be exported to the errored_coverages_file to be assessed later
        """

        # ensure there is a mapping to the Canvas Payer
        payer_org_id = self.payer_map.get(f"{row['insurance_company']}|{row['insurance_payer_id']}")
        if not payer_org_id:
            with open(self.ignored_coverages_file, 'a') as ignored:
                # id|patient_key|rank|insurance_name|payer_id|existing_coverages
                ignored.write(f"{_id}|{patient_key}|{rank}|{row['insurance_company']}|{row['insurance_payer_id']}|\n")
                print('   No payer...ignoring')
            return

        # save insurance cards
        self.ingest_document(_id, patient_key, 'photo_front', row, rank)
        self.ingest_document(_id, patient_key, 'photo_back', row, rank)

        # skip over any coverages already done to avoid duplicates
        key = f"{_id}|{rank}"
        if key in self.done_coverages:
            print('   Already done...skipping')
            return

        # try to find the subscriber of the coverage
        # export row to errored_coverages_file if it failed to find the subscriber in Canvas
        try:
            subscriber = self.find_subscriber(row, patient_key)
        except Exception as e:
            e = str(e).replace('\n', '')
            with open(self.errored_coverages_file, 'a') as errored:
                errored.write(f"{_id}|{patient_key}|{rank}|{e}\n")
            print('   Error with subscriber')
            return
        
        relationship_mapping = {
            '19': 'child',
            '01': 'spouse',
            'G8': 'other',
            '18': 'self',
            '41': 'injured'
        }
        order_mapping = {
            "primary_insurance": 1,
            "secondary_insurance": 2,
            "tertiary_insurance": 3
        }
    
        payload = {
          "resourceType": "Coverage",
          "order": order_mapping[rank],
          "status": "active",
          "subscriber": {
            "reference": f"Patient/{subscriber}"
          },
          "subscriberId": row['insurance_id_number'],
          "beneficiary": {
            "reference": f"Patient/{patient_key}"
          },
          "relationship": {
            "coding": [
              {
                "system": "http://hl7.org/fhir/ValueSet/subscriber-relationship",
                "code": "self" if row['is_subscriber_the_patient'] else relationship_mapping.get(row['patient_relationship_to_subscriber'], 'other')
              }
            ]
          },
          "payor": [
            {
              "reference": f"Organization/{payer_org_id}",
              "type": "Organization",
            }
          ],
          "class": (
            ([{
              "type": {
                "coding": [
                  {
                    "system": "http://hl7.org/fhir/ValueSet/coverage-class",
                    "code": "plan"
                  }
                ]
              },
              "value": row['insurance_plan_name']
            }] if row['insurance_plan_name'] else []) +
            ([{
              "type": {
                "coding": [
                  {
                    "system": "http://hl7.org/fhir/ValueSet/coverage-class",
                    "code": "group"
                  }
                ]
              },
              "value": row['insurance_group_number']
            }] if row['insurance_group_number'] else [])
          ),
            "period": {
                "start": self.start_date
            }
        }
        # print(json.dumps(payload, indent=2))
        try:
            canvas_id = self.fumage_helper.perform_create(payload)
            with open(self.done_coverages_file, 'a') as done:
                done.write(f"{_id}|{patient_key}|{rank}|{canvas_id}\n")
            print(f'   Done with {rank}')
        except BaseException as e:            
            e = str(e).replace('\n', '')
            with open(self.errored_coverages_file, 'a') as errored:
                errored.write(f"{_id}|{patient_key}|{rank}|{e}\n")
            print(f'   Error on {rank}')

    def ingest_document(self, _id, patient_key, image_key, row, insurance):
        """
            Some coverages had a front/back image card that Canvas will save as 
            a Patient Administrative Document with the FHIR DocumentReference endpoint

            image_key will either be photo_front or photo_back

            This function will export any documents that failed in the errored_documents_file
            and will export all the successful documents in the done_documents_file so no duplicates
            are loaded and for tracking. 
        """
        key = f"{_id}|{insurance}|{image_key}"
        if key in self.done_documents or not row[image_key]:
            print(f'   No {image_key} needed now')
            return

        # since we are reading out of a CSV the image s3 link is expired, so we have to fetch a new link
        record = self.drchrono_records.get(key)
        if not record:
            try:
                record = self.drchrono_helper.fetch_single_drchrono_record('patients', _id)
                f = record[insurance]
                self.drchrono_records[key] = record
            except Exception as e:
                e = str(e).replace('\n', '')
                with open(self.errored_documents_file, 'a') as errored:
                    errored.write(f"{_id}|{patient_key}|{insurance}|{image_key}|{e}\n")
                print(f'   Errored {image_key} card')
                return

        if not record[insurance][image_key]:
            return

        r = requests.get(record[insurance][image_key])
        # convert image to PDF
        image = Image.open(io.BytesIO(r.content))
        pdf_io = io.BytesIO()  # Use in-memory buffer to save PDF
        image.save(pdf_io, format="PDF")
        pdf_io.seek(0)
        
        if r.status_code != 200:
            with open(self.errored_documents_file, 'a') as errored:
                errored.write(f"{_id}|{patient_key}|{insurance}|{image_key}|{r.text}\n")
            print(f'   Errored {image_key} card')
            return

        payload = {
            "resourceType": "DocumentReference",
            "extension": [
                {
                    "url": "http://schemas.canvasmedical.com/fhir/document-reference-comment",
                    "valueString": "Insurance Card Back" if image_key == 'photo_back' else "Insurance Card Front"
                },
                {
                    "url": "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date",
                    "valueDate": "2024-09-13"
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
                        "code": "64290-0"
                    }
                ]
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://schemas.canvasmedical.com/fhir/document-reference-category",
                            "code": "patientadministrativedocument"
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
            "description": "Insurance Card",
            "content": [
                {
                    "attachment": {
                        "contentType": "application/pdf",
                        "data": base64.b64encode(pdf_io.read()).decode('utf-8')
                    }
                }
            ]
          }
        
        # print(json.dumps(payload, indent=2))
        try:
            canvas_id = self.fumage_helper.perform_create(payload)
            with open(self.done_documents_file, 'a') as done:
                done.write(f"{_id}|{patient_key}|{insurance}|{image_key}|{canvas_id}\n")
            print(f'   Done {image_key} card')
        except BaseException as e:
            e = str(e).replace('\n', '')
            with open(self.errored_documents_file, 'a') as errored:
                errored.write(f"{_id}|{patient_key}|{insurance}|{image_key}|{e}\n")
            print(f'   Errored {image_key} card')

    
    def coverages_already_found(self, drchrono_patient_id, canvas_patient_key, drchrono_coverages):
        """
            This function was added because the data migration happened after the customer
            went live in Canvas. We needed to skip over patients who already had coverages manually
            added to their profile with the assumption that manually entered coverages
            would be more up to date than any historical. 

            Any patients skipped will be added to the ignore file to review after.
        """

        search_parameters = {
            "patient": f"Patient/{canvas_patient_key}",
            "status": "active"
        }
        response = self.fumage_helper.search('Coverage', search_parameters)

        # if any response comes back as a failure, add to the errored file to 
        # go back and review and potentially replay
        if response.status_code != 200:
            e = (f"Failed to find coverages with {response.url} and error {response.text}").replace('\n', '')
            with open(self.errored_coverage_file, 'a') as errored:
                errored.write(f"{drchrono_patient_id}|{canvas_patient_key}||{e}\n")
                print('   Errored response')
            return True


        total = response.json()['total']
        if total:
            if all([r['resource'].get('period', {}).get('start') == self.start_date for r in response.json()['entry']]):
                return False # this is canvas loading right now, we only care about ones they entered manually
            data = response.json()['entry']
            with open(self.ignored_coverages_file, 'a') as ignored:
                #id|patient_key|rank|insurance_name|payer_id|existing_coverages
                ignored.write(f"{drchrono_patient_id}|{canvas_patient_key}||||Found existing coverages: {data}\n")
            print('   Canvas coverages found...skipping')
            return True

        return False
    
    def load(self):
        """
            Loop through all the patients to load their coverage information
        """ 
        patient_count = len(self.patient_map)
        for i, (drchrono_patient_id, canvas_patient_key) in enumerate(self.patient_map.items()):

            print(f'Creating Historical Records for {drchrono_patient_id}/{canvas_patient_key} ({i+1}/{patient_count})')

            # we have determined to already ignore this patient so skip over
            if f'{drchrono_patient_id}|' in self.ignored_coverages:
                print('   Already determined to ignore')
                continue

            # Need to skip patients that already have coverage manually entered
            if self.coverages_already_found(drchrono_patient_id, canvas_patient_key, self.coverages.get(drchrono_patient_id, [])):
                continue
            
            self.ingest_coverages(canvas_patient_key, self.coverages.get(drchrono_patient_id, []))

                
        print('Done')


    def replay_errored_coverages(self):
        """
            After the load is complete, go through the errored file
            and pull out the rows that you need replayed. 
        """

        errored_rows = fetch_from_csv(self.errored_coverages_file, key='id', delimiter='|')

        count = len(errored_rows)
        for i, (drchrono_patient_id, row) in enumerate(errored_rows.items()):
            row = row[0]

            # rows with this `Failed to find subscriber` error mesage are ignored
            # and needed to be manually addressed because our script could not find
            # a patient in Canvas that was the coverage's subscriber
            if 'Failed to find subscriber' not in row['error_message']:
                continue

            canvas_patient_key = row['patient_key']
            print(f'Rerunnning for {drchrono_patient_id}/{canvas_patient_key}/{row["rank"]} ({i+1}/{count})')

            patient_coverage = next((c for c in self.coverages.get(drchrono_patient_id, []) if c['id'] == drchrono_patient_id), None)
            self.ingest_specific_coverage(patient_coverage['id'], canvas_patient_key, row["rank"], eval(patient_coverage[row['rank']]))
                
        print('Done')


if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = CoverageLoader(environment="customer_identifier")

    # create the coverages file or fetch the already existing CSV
    loader.fetch_coverage_information()

    # create a payer mapping template file to populate. 
    # there is some manual mapping to accomplish from DrChrono's 
    # insurance company/payer id to Canvas payer organization
    # once this file is made, we will need to go in and add the value mappings
    loader.make_payer_mapping_file()

    loader.load()
    # loader.replay_errored_coverages()