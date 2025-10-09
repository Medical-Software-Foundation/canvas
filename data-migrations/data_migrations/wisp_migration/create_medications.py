import csv, re, json, os
from pathlib import Path
from collections import defaultdict
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings, write_to_json
from data_migrations.template_migration.medication import MedicationLoaderMixin
from data_migrations.template_migration.mapping_review import MedicationReview
import sys
from itertools import islice
from datetime import datetime

# Set max field size limit
csv.field_size_limit(sys.maxsize)

class MedicationLoader(MedicationLoaderMixin, MedicationReview):
    """
    Load Medications from Vendor EMR to Canvas.
    """

    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'medications'

        self.patient_map_file = 'PHI/patient_id_map.json'
        self.note_map_file = "mappings/historical_note_map.json"
        self.medication_map_file = "mappings/medication_coding_map.json"
        self.json_file = f"PHI/{self.data_type}.json"
        self.json_file_prefix = f"PHI/medications/{self.data_type}_"
        self.csv_file = f'PHI/{self.data_type}.csv'
        self.customer_file = f'PHI/customer_{self.data_type}.csv'
        self.validation_error_file = f'results/errored_{self.data_type}_validation.json'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.done_file = f'results/done_{self.data_type}.csv'
        self.ignore_file = f'results/ignored_{self.data_type}.csv'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)


        # self.done_records = fetch_complete_csv_rows(self.done_file)
        self.patient_map = fetch_from_json(self.patient_map_file)
        # self.note_map = fetch_from_json(self.note_map_file)
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.medication_map = fetch_from_json(self.medication_map_file)

        # any defaults needed for mapping/creation
        self.default_location = "24b50061-cdb7-47ec-85ea-c1b41f9805b3"
        self.default_note_type_name = "Vendor Data Migration"
        super().__init__(*args, **kwargs)

    def create_medication_map(self):
        """
        Create the medication map from the data source and save it to the medication_map_file
        The key of the map should be the medication text and the rxnorm code separated by a pipe
        """
        medication_map = fetch_from_json(self.medication_map_file)

        # TODO: Pick your option depending on your data source

        # If you are extracting data from your vendors API, you can make a 
        # helper class to perform the extraction
        # data = self.vendor_helper.fetch_medications()

        # If your data is in a JSON file, you can load it from the file
        # data = fetch_from_json(self.json_file)

        # If your data is already in a CSV file then loop through the 
        # file and map the data to the template format
        data = []
        with open(self.customer_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                data.append(row)

        for medication in data:
            medication_text = medication.get("Name", "")
            medication_rxnorm_code = medication.get("Rx Identifier Value", "")

            mapping_key = f"{medication_text}|{medication_rxnorm_code}"

            if mapping_key in self.medication_map:
                continue

            if medication_rxnorm_code == 'Compound':
                medication_map[mapping_key] = "unstructured"
            else:
                medication_map[mapping_key] = []

        write_to_json(self.medication_map_file, medication_map)

    def chunk_dict(self, d, size):
        """Yield successive chunks from a dictionary."""
        it = iter(d.items())
        for _ in range(0, len(d), size):
            yield dict(islice(it, size))


    def make_json(self, delimiter='|'):
        """
        Fetch the Medication Records from Vendor API
        and convert the JSON into a CSV with the columns that match
        the Canvas Data Migration Template
        """

        # Patient Identifier System,
        # Patient Identifier Value,
        # Status,
        # Name,
        # Prescription ID,
        # Rx Identifier System,
        # Rx Identifier Value,
        # Sig


        data = defaultdict(list)
        with open(self.customer_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                patient_id = row['Patient Identifier Value']
                try:
                    canvas_patient_key, canvas_patient_id = self.map_patient(patient_id)
                except BaseException as e:
                    self.ignore_row(row['Prescription ID'], f"No patient {patient_id} to map internal note {row['Prescription ID']}")
                    continue

                medication_text = row["Name"]
                medication_rxnorm_code = row["Rx Identifier Value"]
                mapping_key = f"{medication_text}|{medication_rxnorm_code}"

                if mapping_found := self.medication_map.get(mapping_key):
                    if mapping_found == 'unstructured':
                        codings = [{
                            "system": "unstructured",
                            "code": "N/A",
                            "display": medication_text
                        }]
                    elif "multiple" in mapping_found:
                        codings = [i['coding'] for i in mapping_found['multiple']]
                    else:
                        codings = [mapping_found['coding']]
                else:
                    self.ignore_row(row['Prescription ID'], f"No mapping found for {mapping_key}")
                    continue


                pattern = r"^(.*?)\.\s*(Directions:.*)$"
                match = re.match(pattern, row['Sig'], flags=re.DOTALL)

                if not match:
                    self.ignore_row(row['Prescription ID'], f"Unable to split Sig {row['Sig']}")
                    continue

                created = match.group(1)
                directions = match.group(2)

                for coding in codings:
                    data[patient_id].append({
                        "ID": row['Prescription ID'],
                        "Canvas Patient Key": canvas_patient_key,
                        "Canvas Patient ID": canvas_patient_id,
                        "Status": row['Status'],
                        "Coding": coding,
                        "Created": created,
                        "SIG": directions,
                    })

        chunk_size = 100000
        for idx, chunk in enumerate(self.chunk_dict(data, chunk_size), start=1):
            file_path = f"{self.json_file_prefix}{idx}.json"
            write_to_json(file_path, chunk)

        write_to_json(self.json_file, data)

        print("JSON successfully made")

    def combine_sig(self, row):
        limit_reached = False
        sig_text = row['SIG']
        created_dates = row['Created']
        
        # Create original sig with dates
        if created_dates:
            dates_str = '\n'.join(created_dates)
            original_sig = f"{sig_text}\n{dates_str}"
        else:
            original_sig = sig_text


        # Only apply formatting if original is over 255 characters
        if len(original_sig) > 255:
            # Remove "Directions:" prefix if present
            sig_text = sig_text.replace("Directions:", "").strip()

            # Format created dates
            if created_dates:
                if len(created_dates) == 1:
                    formatted_dates = f"Created on {created_dates[0]}"
                else:
                    # Extract just the dates (remove "Created on " prefix)
                    dates_only = [date.replace("Created on ", "") for date in created_dates]
                    dates_joined = ',\n'.join(dates_only)
                    formatted_dates = f"Created on:\n{dates_joined}"
            else:
                formatted_dates = ""

            # Combine sig and dates
            full_sig = f"{sig_text}\n{formatted_dates}" if formatted_dates else sig_text

            # Truncate if over 255 characters
            if len(full_sig) > 255:
                limit_reached = True
        else:
            # Use original formatting if under 255 characters
            full_sig = original_sig

        return full_sig, limit_reached

    def combine_json_file(self):
        # Directory with your JSON files
        input_dir = Path("PHI/medications")
        output_file = Path("combined.json")

        combined = {}

        for file in sorted(input_dir.glob("failed_combined_medications_*.json")):
            with open(file, "r") as f:
                data = json.load(f)

                if not isinstance(data, dict):
                    raise ValueError(f"{file} is not a dict!")

                # Merge dicts; later files overwrite earlier keys if duplicates exist
                combined.update(data)

        print(f"Merged {len(list(input_dir.glob('*.json')))} JSON files into {len(combined)} keys")
        write_to_json(f"PHI/medications/failed_sig.json", combined)

    def get_counts(self, new_file, failed_filename):
        long_records = {}
        new_record_count = 0
        with open(new_file, "r") as f:
            data = json.load(f)
            c = 0
            for patient_id, records in data.items():
                c += len(records)

                long_patient_records = []
                for row in records:
                    new_sig, limit_reached = self.combine_sig(row)
                    if limit_reached:
                        row['combined_sig'] = new_sig
                        long_patient_records.append(row)

                if long_patient_records:
                    long_records[patient_id] = long_patient_records
                    new_record_count += len(long_patient_records)

        if long_records:
            write_to_json(failed_filename, long_records)
            print(f"Error file has {new_record_count} records")

        print(f"Already found {new_file} and has {c} records")

    def sort_and_combine_json(self):

        count = 0

        for file in Path(f"PHI/{self.data_type}").glob("medications_*.json"):
            file_split = str(file).split('/')
            file_split[-1] = f"combined_{file_split[-1]}"
            new_file = "/".join(file_split)
            if os.path.isfile(new_file):
                file_split[-1] = f"failed_{file_split[-1]}"
                failed_filename = "/".join(file_split)
                self.get_counts(new_file, failed_filename)
                continue

            print(file)
            with open(file, "r") as f:
                data = json.load(f)
                new_data = {}

                for patient_id, records in data.items():

                    grouped = defaultdict(list)

                    # group rows by coding
                    for r in records:
                        grouped[str(r["Coding"])].append(r)

                    combined = []
                    for coding_key, items in grouped.items():
                        # sort items by created date
                        def extract_date(created_str: str) -> datetime:
                            return datetime.strptime(created_str.replace("Created on ", ""), "%Y-%m-%d")

                        created_list = sorted(
                            {i["Created"] for i in items},  # set removes duplicates
                            key=extract_date
                        )

                        ids = [i['ID'] for i in items]

                        # pick the item with the latest created date for directions
                        latest_item = max(items, key=lambda x: extract_date(x["Created"]))

                        combined.append({
                            **latest_item,
                            "IDs": ids,
                            "ID": f"{patient_id}-{latest_item['Coding'][0]['display'] if isinstance(latest_item['Coding'], list) else latest_item['Coding']['display']}",
                            "Created": created_list
                        })

                    # sort combined by first created date (optional)
                    combined = sorted(combined, key=lambda x: x["Created"][0])
                    new_data[patient_id] = combined

                    count += len(combined)
            print(f"File has {len(combined)} records")

            write_to_json(new_file, new_data)


        print(f"Unique medications to create {count}")


if __name__ == '__main__':
    # TODO: Change to your environment name from config.ini
    loader = MedicationLoader(environment='hellowisp')
    delimiter = ','

    # Create the medication map from the unique set of medications found in the data source
    # loader.create_medication_map()

    # Now that the medication map is created, you can use the `map` function to search for the 
    # medication text/rxnorm code and map the data to the template format
    # loader.map()

    # After the search has been complete, there will be some items that need manual review and decisions        
    # to map the medication to the correct coding. 
    # loader.review()
    
    # Step 1: Make the Vendor API call to their Medications endpoint and convert the JSON return
    # to the template CSV loader
    # loader.make_json(delimiter=delimiter)
    # loader.sort_and_combine_json()
    loader.combine_json_file()
    
    # Step 2: Validate the CSV values with the Canvas template data migration rules
    # valid_rows = loader.validate(delimiter=delimiter)
    
    # Step 3: If you are ready to load the rows that have passed validation to your Canvas instance
    # loader.load(valid_rows)
