import csv

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.utils import (
    fetch_from_json,
    write_to_json,
    load_fhir_settings,
    fetch_from_csv,
    fetch_complete_csv_rows
)
from data_migrations.template_migration.utils import validate_date
from data_migrations.template_migration.hpi import HPILoaderMixin
from data_migrations.template_migration.plan import PlanLoaderMixin
from data_migrations.template_migration.questionnaire_response import QuestionnaireResponseLoaderMixin

class NoteTemplateLoader(HPILoaderMixin, PlanLoaderMixin, QuestionnaireResponseLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'notes'
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f"PHI/{self.data_type}.csv"
        self.ignore_file = f"results/ignored_{self.data_type}.csv"
        self.done_file = f'results/done_{self.data_type}.csv'
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'
        self.fumage_helper = load_fhir_settings(environment=environment)
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map = fetch_from_json(self.patient_map_file) 

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        self.default_note_type_name = "Avon Historical Note"

    def get_manual_input(self, row):
        dos_string = input(f"What should the date in YYYY-MM-DD be for {row['name']}: ")
        valid, dos = validate_date(dos_string, 'DOS')
        return dos

    def make_csv(self, delimiter="|"):
        data = self.avon_helper.fetch_records(f"v2/{self.data_type}", self.json_file, param_string='')

        headers = [
            "ID",
            "Patient Identifier",
            "Appointment ID",
            "RFV",
            "DOS",
            "Provider",
            "HPI ID",
            "HPI Response",
            "Plan ID",
            "Plan Response",
            "Physical Exam ID",
            "Physical Exam Response"
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:

                # the note templates seem to have names like
                # Follow Up Visit Note - Mar 7, 2024
                # Follow Up Visit Note: Mar 7, 2024
                # so we need to get the RFV and DOS from these strings
                try:
                    if '-' in row['name']:
                        _, dos = row['name'].split('-')
                    else:
                        _, dos = row['name'].split(':')

                    valid, dos = validate_date(dos.strip(), 'DOS')
                    if not valid:
                        dos = self.get_manual_input(row)
                except:
                    dos = self.get_manual_input(row)

                appointment_id = row['appointment']
                created_by = row['created_by']
                csv_row = {
                    "ID": row['id'],
                    "Patient Identifier": row['patient'],
                    "Appointment ID": appointment_id,
                    "RFV": row['name'],
                    "DOS": f'{dos}T09:00:00-05:00',
                    "Provider": created_by
                }
                # print(row)
                for section in row['sections']:
                    for answer in section['answers']:
                        if answer['response']:
                            csv_row[f"{answer['name']} ID"] = answer['id']
                            csv_row[f"{answer['name']} Response"] = answer['response']
                        else:
                            self.ignore_row(answer["id"], "Response to answer not given")
                writer.writerow(csv_row)

        print("Successfully made CSV")

    def ingest_notes(self, delimiter="|"):

        self.notes_template_map = fetch_from_json("mappings/notes_template_map.json")

        ids = set()
        with open(self.csv_file, "r") as file:
            reader = csv.DictReader(file, delimiter=delimiter)
            rows = list(reader)
            appointments = fetch_from_csv("results/done_appointments.csv", key='id', delimiter=delimiter)
            total_count = len(rows)
            print(f'      Found {len(rows)} records')
            for i, row in enumerate(rows):
                print(f'Ingesting ({i+1}/{total_count})')

                patient = row['Patient Identifier']
                patient_key = ""
                try:
                    # try mapping required Canvas identifiers
                    patient_key = self.map_patient(patient)
                    if row['Appointment ID']:
                        apt_map = appointments.get(row['Appointment ID'])
                        if apt_map:
                            # grab the note_id of the appointment 
                            read_response = self.fumage_helper.read("Appointment", apt_map[0]['canvas_externally_exposable_id'])
                            if read_response.status_code != 200:
                                raise Exception("Failed to find appointment note to lock")
                            note_id = read_response.json()["extension"][0]['valueId']
                        else:
                            self.error_row(f"{row['ID']}|{row['Patient Identifier']}|", f"Appointment note {row['Appointment ID']} not found in Canvas yet")
                            continue
                    elif row['ID'] in self.notes_template_map:
                        note_id = self.notes_template_map[row['ID']]
                    else:
                        practitioner_key = self.map_provider(row.get('Provider'))
                        note_id = self.create_note(patient_key, **{
                            "note_type_name": self.default_note_type_name,
                            "provider_key": practitioner_key,
                            "encounter_start_time": row['DOS'],
                            "practice_location_key": self.default_location,
                            "title": row.get("RFV")
                        })
                        self.notes_template_map[row['ID']] = note_id
                        write_to_json("mappings/notes_template_map.json", self.notes_template_map)
                except BaseException as e:
                    self.ignore_row(row['ID'], e)
                    continue

                command_row = {
                    "Patient Identifier": row['Patient Identifier'],
                    "DOS": row['DOS'],
                    "Provider": row["Provider"] if row["Provider"] != "user_null" else "5eede137ecfe4124b8b773040e33be14",
                    "Note Type Name": self.default_note_type_name,
                    "Note ID": note_id,
                }

                if row['HPI ID']:
                    hpi_row = {
                        **command_row,
                        "ID": row['HPI ID'],
                        "Narrative": row['HPI Response'],
                        "Note ID": note_id
                    }
                    HPILoaderMixin.load_via_commands_api(self, [hpi_row])
                    ids.add(hpi_row['ID'])

                if row['Plan ID']:
                    plan_row = {
                        **command_row,
                        "ID": row['Plan ID'],
                        "Narrative": row['Plan Response'],
                        "Note ID": note_id
                    }
                    PlanLoaderMixin.load_via_commands_api(self, [plan_row])
                    ids.add(plan_row['ID'])
                
                if row['Physical Exam ID']:
                    sa_row = {
                        **command_row,
                        "ID": row['Physical Exam ID'],
                        "Note ID": note_id,
                        "Questionnaire ID": "ff101e83-4e74-4369-819b-11dcddb61292",
                        "Questions": {
                            "9487374e-e662-4d7e-9f33-d7803d4b054b": [{"valueString": row['Physical Exam Response']}]
                        }
                    }
                    QuestionnaireResponseLoaderMixin.load(self, [sa_row])
                    ids.add(sa_row['ID'])

                # input('Continue?')


if __name__ == "__main__":
    loader = NoteTemplateLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    loader.ingest_notes(delimiter)
