import csv, re, arrow
from data_migrations.utils import fetch_from_json, fetch_complete_csv_rows, load_fhir_settings, write_to_json, strip_html
from data_migrations.template_migration.plan import PlanLoaderMixin
from collections import defaultdict

import sys

# Set max field size limit
csv.field_size_limit(sys.maxsize)

class PlanNotesLoader(PlanLoaderMixin):


    def __init__(self, environment, *args, **kwargs):
        self.data_type = "plan_notes"
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.original_csv_file = f'PHI/customer_{self.data_type}.csv'
        self.json_file = f"PHI/{self.data_type}.json"
        self.error_file = f'results/PHI/errored_{self.data_type}.csv'
        self.done_file = f'results/PHI/done_{self.data_type}.csv'
        self.ignore_file = f"results/ignored_{self.data_type}.csv"
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'

        self.environment = environment
        self.fumage_helper = load_fhir_settings(environment)

        self.notes_map = fetch_from_json("mappings/notes_map.json")
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map = {"1": "3537ec406ed44068b3b59ee28389a0a0"} #fetch_from_json(self.patient_map_file) 


        self.default_note_type_name = "Historical Data Migration"
        self.default_location = "29e0cff2-fbd8-4add-8a9a-7aa2d9e43594"
        self.note_attributes = {
            "note_type_name": self.default_note_type_name,
            "provider_key": "5eede137ecfe4124b8b773040e33be14",
            "encounter_start_time": "2025-09-30T09:00:00-04:00", # 9am on go live date
            "practice_location_key": self.default_location,
        }


    def make_json(self, delimiter=','):

        data = defaultdict(list)

        # csv columns
        # id,provider_id,created,body,patient_id
        with open(self.original_csv_file, 'r') as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            for row in reader:
                data[row['patient_id']].append({
                    "ID": row['id'],
                    "Provider": row['provider_id'],
                    "Date": row['created'],
                    "Text": strip_html(row['body'])
                })

        write_to_json(self.json_file, data)

    def load(self):

        ids = set()

        data = fetch_from_json(self.json_file)

        total_count = len(data)
        print(f'      Found {total_count} patients')
        ids = set()
        count = 1
        for patient_id, rows in data.items():
            print(f'Ingesting ({count}/{total_count})')

            patient_key = ""
            try:
                patient_key = self.map_patient(patient_id)
            except BaseException as e:
                self.ignore_row(patient_id, e)
                continue

            print(f' Looking at patient {patient_key}')

            # see if patient already has a plan note to insert into 
            note_id = self.notes_map.get(patient_key)
            if not note_id:
                # if not create the note and add it to mapping
                note_id = self.create_note(patient_key, **self.note_attributes)
                self.notes_map[patient_key] = note_id
                write_to_json("mappings/notes_map.json", self.notes_map)

            for row in rows:
                if row['ID'] in ids or row['ID'] in self.done_records:
                    print(' Already did record')
                    continue

                provider_name = ""
                try:
                    provider_name = self.map_provider(row['Provider'])
                except BaseException as e:
                    self.ignore_row(patient_id, e)
                    continue

                try:
                    date = arrow.get(row['Date']).format("M/D/YY [at] h:mm A")
                except BaseException as e:
                    self.error_row(f"{row['ID']}|{patient_id}|{patient_key}", e)

                plan_row = {
                    "Patient Identifier": patient_id,
                    "ID": row['ID'],
                    "Narrative": f"Provider: {provider_name}\nDate: {date} UTC\n{row['Text']}",
                    "Note ID": note_id
                }
                PlanLoaderMixin.load_via_commands_api(self, [plan_row], perform_nsce=False)
                ids.add(plan_row['ID'])

                # print(plan_row)
            return

            count += 1



if __name__ == '__main__':
    # change the customer_identifier to what is defined in your config.ini file
    loader = PlanNotesLoader(environment='hellowisp')
    delimiter = ','

    # Convert customer file to the template CSV loader
    #loader.make_json(delimiter=delimiter)
    
    loader.load()
