import csv
import os

from data_migrations.avon_migration.utils import AvonHelper
from data_migrations.template_migration.message import MessageLoaderMixin
from data_migrations.utils import fetch_complete_csv_rows, fetch_from_json, reverse_mapping
from data_migrations.utils import load_fhir_settings


class MessageLoader(MessageLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.data_type = 'message_threads'
        self.environment = environment
        self.avon_helper = AvonHelper(environment)
        self.json_file = f"PHI/{self.data_type}.json"
        self.csv_file = f"PHI/{self.data_type}.csv"
        self.ignore_file = f"results/ignored_{self.data_type}.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file) 
        self.done_file = f'results/done_{self.data_type}.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.error_file = f'results/errored_{self.data_type}.csv'
        self.fumage_helper = load_fhir_settings(environment)

        self.doctor_map = fetch_from_json("mappings/doctor_map.json")
        self.validation_error_file = f'results/PHI/errored_{self.data_type}_validation.json'

        self.default_location = "9e757329-5ab1-4722-bab9-cc25002fa5c0"
        super().__init__(*args, **kwargs)


    def make_csv(self, delimiter='|') -> None:
        if os.path.isfile(self.csv_file):
            print('CSV already exists')
            return None

        data = self.avon_helper.fetch_records("v2/message_threads", self.json_file, param_string='')

        headers = [
            "ID",
            "Timestamp",
            "Recipient",
            "Sender",
            "Text",
            "Thread ID",
            "Patient Identifier",
            "Patient Key"
        ]

        with open(self.csv_file, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()

            for row in data:

                if not row['messages']:
                    self.ignore_row(row['id'], "Message thread contains no messages")
                    continue

                # If a patient is on the thread, see if we have a Canvas patient mapping
                patient_key = None
                patient_count = 0
                if patient := row['patient']:
                    try:
                        patient_key = self.map_patient(patient)
                        patient_count += 1
                    except BaseException as e:
                        self.error_row(f"{row['id']}|{patient}|{patient_key}", f"Main patient: {e}")
                        continue
                
                # make sure we have a provider mapping to Canvas for the participants in the thread
                participant_map = {}
                for participant in row['participants']:
                    if participant == patient:
                        continue
                    if participant in self.patient_map:
                        patient = participant
                        patient_key = self.map_patient(participant)
                        patient_count += 1
                        continue
                    try:
                        participant_map[participant] = self.map_provider(participant)
                    except:
                        continue

                if not participant_map:
                    self.error_row(f"{row['id']}|{patient}|{patient_key}", f"Unable to find any providers in the message thread")
                    continue

                if patient_count > 1:
                    self.error_row(f"{row['id']}|{patient}|{patient_key}", f"Multiple patients")
                    continue
                elif not patient_count:
                    self.error_row(f"{row['id']}|{patient}|{patient_key}", "Patient not ingested yet")
                    continue

                previous_provider = None
                for message in row['messages']:

                    if message['type'] not in ('in_app_message', 'text_message'):
                        self.ignore_row(message['id'], f"Message of type {message['type']} are ignored")
                        continue

                    if not message['text']:
                        self.ignore_row(message['id'], f"Message does not contain any text")
                        continue

                    # need to map sender/recipient to patient/staff members
                    try:
                        created_by = message['created_by']
                        recipient = None
                        if patient == created_by:
                            sender = f'Patient/{patient_key}'
                        elif created_by in self.patient_map:
                            self.error_row(f"{message['id']}|{patient}|{patient_key}", "More than one patient in thread")
                        else:
                            provider = participant_map.get(created_by) or self.map_provider(created_by)
                            sender = f'Practitioner/{provider}'
                            recipient = f'Patient/{patient_key}'
                            previous_provider = provider

                        if not recipient:
                            recipient = f"Practitioner/{previous_provider or list(participant_map.values())[0]}"

                    except BaseException as e:
                        self.error_row(f"{message['id']}|{patient}|{patient_key}", e)
                        continue

                    row_to_write = {
                        "ID": message['id'],
                        "Timestamp": message['created_at'],
                        "Recipient": recipient,
                        "Sender": sender,
                        "Text": message['text'],
                        "Thread ID": row['id'],
                        "Patient Identifier": patient,
                        "Patient Key": patient_key
                    }

                    writer.writerow(row_to_write)

            print("CSV successfully made")


if __name__ == "__main__":
    # change the customer_identifier to what is defined in your config.ini file
    loader = MessageLoader(environment='phi-collaborative-test')
    delimiter = '|'

    #loader.make_csv(delimiter=delimiter)
    valid_rows = loader.validate(delimiter=delimiter)
    loader.load(valid_rows)
