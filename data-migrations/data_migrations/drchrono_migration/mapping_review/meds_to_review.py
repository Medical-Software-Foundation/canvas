import json, csv
from data_migrations.utils import fetch_from_json, write_to_json


class MedicationReview:

	"""

	DrChrono seems to have some rxnorm codes that map to different medication names / ndc codes. 

	The first block of code will open a bunch of files to read from. 
	1. The `mapping/medication_coding_map` houses all the responses a FHIR Medication returned for each rxnorm and name pairing found in DrChrono
	2. The `meds_already_reviewed` houses all the codes that have already been manually mapped in this code. So as you make decisions, it will append them to the file and save your progress as you go
	3. The `meds_to_review` houses all the ones that are difficult that you may want to skip and come back to at a later time or ones that should be ingested in Canvas as unstructured free text

	The second block of code will loop through data in #1, find the FHIR Medication responses and ask for you to manually review and that are ambiguous. At the top it will show you the rxnorm|medication name that is seen from the DrChrono Database, then it will display what options in our FHIR Medication came back for that rxnorm code, you must decide:
	- If you want to ignore this mapping / return to a later time type `0` and press enter
	- If you know what to map the medication to, type the number for that option (each option should have a `#)` in front of it)
	- If you have a completely different mapping to insert, go ahead and paste the coding found this needs to look like `[{'system': 'http://www.fdbhealth.com/', 'code': '2-15222', 'display': 'penicillin G pot in dextrose'}]`

	Remember as you select your options, they will outputing in the files mentioned above. If at any time you get disconnected from internet or take a break and come back to it, make sure the kernel is idle and then redo both blocks of code each time so it can fetch the ones you already did. 

	"""

	def __init__(self, environment, *args, **kwargs):
		self.path_to_mapping_file = '../mappings/medication_coding_map.json'
		self.path_to_reviewd_file = 'meds_already_reviewed.csv'
		self.path_to_med_ignore_file = 'meds_ignored.csv'
		self.delimiter = '|'

		self.data = fetch_from_json(path_to_mapping_file)

		with open(self.path_to_reviewd_file) as reviewed:
			reader = csv.DictReader(reviewed, delimiter=self.delimiter)
			already_reviewed = {f"{row['code']}|{row['name']}" for row in reader}
			print(already_reviewed)

		with open(self.path_to_med_ignore_file) as ignore:
			reader = csv.DictReader(ignore, delimiter=self.delimiter)
			to_review = {f"{row['code']}|{row['name']}" for row in reader}

		self.codes_to_skip = already_reviewed | to_review
		self.environment = environment

	def review(self):

		count = 0
		total = len(self.data)
		for key, ls in self.data.items():
		    print(f'Looking at medication row {count}/{total}')
		    count += 1
		    if key in self.codes_to_skip:
		        print(f'skipping..{key}')
		        continue

		    if not ls:
		        with open(self.path_to_med_ignore_file, 'a') as ignore:
		            ignore.write(f"{key}|{ls}\n")
		        continue

		    if 'resource' not in ls[0]:
		        continue

		    print()
		    print(key)
		    options = {}
		    for i, f in enumerate(ls):
		        print(f"{i+1}) {f['resource']['code']['coding']}\n")
		        options[f"{i+1}"] = f['resource']['code']['coding']
		    print()
		    s = input('pick a number, type 0 to ignore, or paste a better mapping you have:')
		    if s == '0':
		        with open(self.path_to_med_ignore_file, 'a') as ignore:
		            ignore.write(f"{key}|{ls}\n")
		    elif s in options:
		        with open(self.path_to_reviewd_file, 'a') as reviewed:
		            reviewed.write(f"{key}|{options[s]}\n")
		    else:
		        with open(self.path_to_reviewd_file, 'a') as reviewed:
		            reviewed.write(f"{key}|{s}\n")

	def update_mapping_with_reviewed_items(self):
		"""now merge the reviewed list with the main one"""

		data = fetch_from_json(path_to_mapping_file)

		with open(self.path_to_reviewd_file) as reviewed:
		    reader = csv.DictReader(reviewed, delimiter=self.delimiter)
		    for row in reader:
		        data[f'{row["code"]}|{row["name"]}'] = row['to_review']

		write_to_json(self.path_to_mapping_file, data)

	def ignore_as_unstructured(self):
		data = fetch_from_json(self.path_to_mapping_file)

		with open(self.path_to_med_ignore_file) as reviewed:
		    reader = csv.DictReader(reviewed, delimiter=self.delimiter)
		    for row in reader:
		        data[f'{row["code"]}|{row["name"]}'] = []

		write_to_json(self.path_to_mapping_file, data)

if __name__ == '__main__':
	# change the customer_identifier to what is defined in your config.ini file
	loader = MedicationReview(environment='customer_identifier')
	loader.review()
	#loader.update_mapping_with_reviewed_items()
	#loader.ignore_as_unstructured()