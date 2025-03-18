import json, csv, requests
from data_migrations.utils import fetch_from_json, write_to_json, get_ontologies_token


class AllergyReview:

	"""

	DrChrono seems to have some allergies that need manual mapping. 

	The `__init__` will open a bunch of files to read from. 
	1. The `data/allergy_coding_map` houses all the responses a FHIR Allergen returned for each rxnorm or description  found in DrChrono
	2. The `allergies_already_reviewed` houses all the codes that have already been manually mapped in this code. So as you make decisions, it will append them to the file and save your progress as you go
	3. The `allergies_ignored` houses all the ones that are difficult that you may want to skip and come back to at a later time or ones that should be ingested in Canvas as unstructured free text

	The `review` function will loop through self.data, 
	find the FHIR Allergen responses and ask for you to manually review and that are ambiguous. 
	At the top it will show you the rxnorm or description that is seen from the DrChrono Database, 
	then it will display what options in our FHIR Allergen came back for that allergy, 
	you must decide:

	- If you want to ignore this mapping / return to a later time type `0` and press enter
	- If you know what to map the allergy to, type the number for that option (each option should have a `#)` in front of it)
	- If the allergy description is too generic, type `g` to use the `"No Allergy Information Available"` coding.
	- If you have a completely different mapping to insert, go ahead and paste the FDB coding found this needs to look like 
	    `[{'system': 'http://www.fdbhealth.com/', 'code': '2-15222', 'display': 'penicillin G pot in dextrose'}]`. 

	Remember as you select your options, they will outputing in the files mentioned above. 
	So your progress is being saved at all times if you exit out or it errors for any reason. 
	Once you go again it will pick up where you left off. 

	"""

	def __init__(self, environment, *args, **kwargs):
		self.path_to_mapping_file = '../mappings/allergen_coding_map.json'
		self.path_to_reviewed_file = 'allergies_already_reviewed.csv'
		self.path_to_ignored_file = 'allergies_ignored.csv'
		self.delimiter = '|'

		self.data = fetch_from_json(self.path_to_mapping_file)

		with open('allergies_already_reviewed.csv') as reviewed:
		    reader = csv.DictReader(reviewed, delimiter=self.delimiter)
		    self.already_reviewed = {row['allergy'] for row in reader}

		with open('allergies_ignored.csv') as ignore:
		    reader = csv.DictReader(ignore, delimiter=self.delimiter)
		    self.to_review = {row['allergy'] for row in reader}

		self.codes_to_skip = already_reviewed | to_review
		self.environment = environment
		self.token = get_ontologies_token(environment)

	def review(self):

		count = 0
		total = len(self.data)
		for key, ls in self.data.items():
		    print(f'Looking at allergy {count}/{total}')
		    count += 1
		    if key in self.codes_to_skip:
		        print(f'skipping..{key}')
		        continue

		    if ls and 'resource' not in ls[0]:
		        continue

		    print()
		    print(key)
		    print()
		        
		    response = requests.request(
		        "GET", 
		        f"https://{self.environment}.canvasmedical.com/ontologies/fdb/allergy/?dam_allergen_concept_id_description__fts={key}", 
		        headers={'Authorization': self.token}, 
		        data={})

		    options = {}
		    if response.status_code != 200:
		        for i, f in enumerate(ls):
		            print(f"{i+1}) {f['resource']['code']['coding']}\n")
		            options[f"{i+1}"] = f['resource']['code']['coding']
		    else:
		        for i, result in enumerate(response.json()['results']):
		            coding = [{'system': 'http://www.fdbhealth.com/', 'code': f'{result["dam_allergen_concept_id_type"]}-{result["dam_allergen_concept_id"]}', 'display': result["dam_allergen_concept_id_description"]}]
		            print(f"{i+1}) {coding}\n")
		            options[f"{i+1}"] = coding
		    
		    print()
		    s = input('pick a number, type 0 to ignore, type g to use the generic mapping, or paste a better mapping you have:')
		    if s == '0':
		        with open(self.path_to_ignored_file, 'a') as ignore:
		            ignore.write(f"{key}|{ls}\n")
		    elif s in options:
		        with open(self.path_to_reviewed_file, 'a') as reviewed:
		            reviewed.write(f"{key}|{options[s]}\n")
		    elif s == 'g':
		        coding = [
		            {
		                "system": "http://www.fdbhealth.com/",
		                "code": "1-143",
		                "display": "No Allergy Information Available"
		            }
		        ]
		        with open(self.path_to_reviewed_file, 'a') as reviewed:
		            reviewed.write(f"{key}|{coding}\n")
		    else:
		        with open(self.path_to_reviewed_file, 'a') as reviewed:
		            reviewed.write(f"{key}|{s}\n")

	def update_mapping_with_reviewed_items(self):
		"""now merge the reviewed list with the main one"""

		data = fetch_from_json(self.path_to_mapping_file)

		with open(self.path_to_reviewed_file) as reviewed:
		    reader = csv.DictReader(reviewed, delimiter=self.delimiter)
		    for row in reader:
		        data[row["allergy"]] = eval(row['to_review'])
		        print(row['allergy'], data[row["allergy"]])

    	write_to_json(self.path_to_mapping_file, data)

    def ignore_and_skip(self):
    	data = fetch_from_json(self.path_to_mapping_file)

    	with open(self.path_to_ignored_file) as reviewed:
    	    reader = csv.DictReader(reviewed, delimiter=self.delimiter)
    	    for row in reader:
    	        data[f'{row["code"]}|{row["name"]}'] = []

    	write_to_json(self.path_to_mapping_file, data)

if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = AllergyReview(environment='customer_identifier')
	loader.review()
	#loader.update_mapping_with_reviewed_items()
	#loader.ignore_and_skip()