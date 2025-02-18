import json, csv
from data_migrations.utils import fetch_from_json, write_to_json


class MedicationReview:

    """
    Lets Map Medication Codes from Customers to FDB Codes

    Files in this folder
    1. The `medication_coding_map` houses all the responses a FHIR Medication 
       returned for each rxnorm and name pairing
    2. The `meds_already_reviewed` houses all the codes that have already been
       manually mapped in this code. So as you make decisions, it will append them to the file and save your progress as you go
    3. The `meds_ignored` houses all the ones that are difficult that you may 
       want to skip and come back to at a later time or ones that should be 
       ingested in Canvas as unstructured free text

    The code will loop through data in #1, find the FHIR Medication responses 
    and ask for you to manually review and that are ambiguous. At the top it 
    will show you the medication name and code that is seen from the customer 
    data, then it will display what options in our FHIR Medication came back for 
    that code, you must decide:
    - If you want to ignore this mapping / return to a later time type `0` and 
      press enter
    - If you know what to map the medication to, type the number for that option 
      (each option should have a `#)` in front of it)
    - If you have a completely different mapping to insert, go ahead and paste 
      the coding found this needs to look like 
      `[{'system': 'http://www.fdbhealth.com/', 'code': '2-15222', 'display': 
      'penicillin G pot in dextrose'}]`

    Remember as you select your options, they will outputing in the files 
    mentioned above. If at any time you get disconnected from internet or take a 
    break and come back to it, make sure the kernel is idle and then redo both 
    blocks of code each time so it can fetch the ones you already did. 
    """

    def __init__(self, *args, **kwargs):
        self.path_to_mapping_file = '../mappings/medication_coding_map.json'
        self.path_to_reviewed_file = 'meds_already_reviewed.csv'
        self.path_to_med_ignore_file = 'meds_ignored.csv'
        self.delimiter = '|'

        self.data = fetch_from_json(self.path_to_mapping_file)

        with open(self.path_to_reviewed_file) as reviewed:
            reader = csv.DictReader(reviewed, delimiter=self.delimiter)
            already_reviewed = {f"{row['name']}|{row['code']}" for row in reader}

        with open(self.path_to_med_ignore_file) as ignore:
            reader = csv.DictReader(ignore, delimiter=self.delimiter)
            to_review = {f"{row['name']}|{row['code']}" for row in reader}

        self.codes_to_skip = already_reviewed | to_review
        print(self.codes_to_skip)


    def review(self):

        count = 0
        total = len(self.data)
        for i, (key, item) in enumerate(self.data.items()):
            print('--------------------------------------------------------')
            print(f'Looking at medication row {i}/{total}')
            if key in self.codes_to_skip:
                print(f'skipping..{key}')
                continue

            if item and isinstance(item[0], dict):
                print(f"Already mapped {key} to {item}\n")
                continue


            count += 1
            print()
            print(key)
            options = {}
            for i, f in enumerate(item):
                print(f"{i+1}) {f}\n")
                options[f"{i+1}"] = f
            print()
            s = input('pick a number, type 0 to ignore, or paste a better mapping you have:')
            if s == '0':
                with open(self.path_to_med_ignore_file, 'a') as ignore:
                    ignore.write(f"{key}|\n")
            elif s in options:
                with open(self.path_to_reviewed_file, 'a') as reviewed:
                    reviewed.write(f"{key}|{options[s]}\n")
            else:
                with open(self.path_to_reviewed_file, 'a') as reviewed:
                    reviewed.write(f"{key}|{s}\n")

        print(count)
        print('DONE!!!')

    def update_mapping_with_reviewed_items(self):
        """now merge the reviewed list with the main one"""

        data = fetch_from_json(path_to_mapping_file)

        with open(self.path_to_reviewed_file) as reviewed:
            reader = csv.DictReader(reviewed, delimiter=self.delimiter)
            for row in reader:
                data[f'{row["name"]}|{row["code"]}'] = row['to_review']

        write_to_json(self.path_to_mapping_file, data)

    def ignore_as_unstructured(self):
        data = fetch_from_json(self.path_to_mapping_file)

        with open(self.path_to_med_ignore_file) as reviewed:
            reader = csv.DictReader(reviewed, delimiter=self.delimiter)
            for row in reader:
                data[f'{row["name"]}|{row["code"]}'] = []

        write_to_json(self.path_to_mapping_file, data)

if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = MedicationReview()
    loader.review()
    #loader.update_mapping_with_reviewed_items()
    #loader.ignore_as_unstructured()