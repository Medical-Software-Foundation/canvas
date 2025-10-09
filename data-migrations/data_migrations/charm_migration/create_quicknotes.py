import csv, json
from datetime import datetime
from zoneinfo import ZoneInfo

from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.utils import fetch_from_json, write_to_json, load_fhir_settings, fetch_complete_csv_rows

from data_migrations.template_migration.questionnaire_response import QuestionnaireResponseLoaderMixin


class QuickNotesLoader(QuestionnaireResponseLoaderMixin):
    def __init__(self, environment, *args, **kwargs):
        self.environment = environment
        self.json_file = "PHI/quicknotes.json"
        self.csv_file = "PHI/quicknotes.csv"
        self.default_location = "e4b42f50-df8d-44a6-931b-1f09f0d7f81b"
        self.provider_name_map_file = "mappings/provider_name_map.json"
        self.provider_name_map = fetch_from_json(self.provider_name_map_file)
        self.patient_map_file = 'PHI/patient_id_map.json'
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.patient_quick_notes_note_map_file = "mappings/quick_notes_note_map.json"
        self.patient_quick_notes_note_map = fetch_from_json(self.patient_quick_notes_note_map_file)
        self.quick_notes_note_name = "Historical Quick Notes"
        self.default_note_type_name = self.quick_notes_note_name # needed to avoid error message with create_note
        self.fumage_helper = load_fhir_settings(environment)
        self.done_file = 'results/done_quicknotes.csv'
        self.done_records = fetch_complete_csv_rows(self.done_file)
        self.ignore_file = "results/ignored_quicknotes.csv"
        self.ignore_records = fetch_complete_csv_rows(self.ignore_file)
        self.error_file = 'results/errored_quicknotes.csv'
        self.validation_error_file = "results/PHI/errored_quicknotes_validation.json"


    def make_json_file(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_file_contents = fetch_from_json("PHI/patients.json")
        patient_ids = [p["patient_id"] for p in patient_file_contents]
        quicknotes = charm_patient_api.fetch_quicknotes(patient_ids=patient_ids)
        write_to_json(self.json_file, quicknotes)

    def make_csv(self):
        data = fetch_from_json(self.json_file)
        headers = [
            "ID",
            "Patient Identifier",
            "DOS",
            "Provider",
            "Location",
            "Note Type Name",
            "Note ID",
            "Note Title",
            "Questionnaire ID",
            "Questions",
        ]
        with open(self.csv_file, "w") as fhandle:
            writer = csv.DictWriter(
                fhandle,
                fieldnames=headers,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()

            for patient_id, patient_quicknotes in data.items():
                for quicknote in patient_quicknotes:
                    provider_id = quicknote["last_modified_by"]
                    quicknotes_provider_name = self.provider_name_map.get(provider_id, "")

                    datetime_of_service = datetime.fromtimestamp(quicknote["last_modified_time"] / 1000)
                    central_time_zone = ZoneInfo("US/Central")
                    date_of_service = datetime_of_service.replace(tzinfo=central_time_zone).date().isoformat()

                    questions = {
                        "343f9db6-9283-437a-9ac8-e00891c41d94": [{"valueString": date_of_service}], # Date
                        "620b8cc3-b45d-477a-a5be-4de08c1380ff": [{"valueString": quicknotes_provider_name}], # Last Modified By
                        "bdaae50d-6b91-4980-9ebd-87a8e8c3bbeb": [{"valueString": quicknote["notes"].encode("ascii", errors="ignore").decode("ascii")}] # Note
                    }

                    row_to_write = {
                        "ID": quicknote["quick_notes_id"],
                        "Patient Identifier": patient_id,
                        "DOS": date_of_service,
                        "Provider": "", # import as canvas-bot
                        "Location": self.default_location,
                        "Note Type Name": "", # not used
                        "Note ID": "", # not used
                        "Note Title": "", # not used
                        "Questionnaire ID": "9d2be041-b5e9-4a14-ab28-f2f08fdfc173",
                        "Questions": json.dumps(questions)
                    }
                    writer.writerow(row_to_write)

        print(f"Successfully made {self.csv_file}")

    def load(self, validated_rows):
        total_count = len(validated_rows)
        print(f'      Found {len(validated_rows)} records')
        ids = set()
        for i, row in enumerate(validated_rows):

            print(f'Ingesting ({i+1}/{total_count})')
            if row['ID'] in ids or row['ID'] in self.done_records or row['ID'] in self.ignore_records:
                print(' Already did record')
                continue

            patient = row['Patient Identifier']
            patient_key = ""

            try:
                patient_key = self.map_patient(patient)
            except BaseException as e:
                self.ignore_row(row['ID'], e)
                continue

            if patient_key not in self.patient_quick_notes_note_map:
                note_id = self.create_note(patient_key, **{
                    "note_type_name": self.quick_notes_note_name,
                    "provider_key": "5eede137ecfe4124b8b773040e33be14", # canvas-bot
                    "encounter_start_time": datetime.now().date().isoformat(),
                    "practice_location_key": self.default_location,
                    "note_title": self.quick_notes_note_name
                })
                self.patient_quick_notes_note_map[patient_key] = note_id
                write_to_json(self.patient_quick_notes_note_map_file, self.patient_quick_notes_note_map)
            else:
                note_id = self.patient_quick_notes_note_map[patient_key]

            questions = json.loads(row["Questions"])

            payload = {
                "resourceType": "QuestionnaireResponse",
                "extension": [
                    {
                        "url": "http://schemas.canvasmedical.com/fhir/extensions/note-id",
                        "valueId": note_id
                    }
                ],
                "questionnaire": f"Questionnaire/{row['Questionnaire ID']}",
                "status": "in-progress",
                "subject": {
                    "reference": f"Patient/{patient_key}",
                    "type": "Patient"
                },
                "authored": row['DOS'],
                "author": {
                    "reference": f"Practitioner/5eede137ecfe4124b8b773040e33be14", # canvas-bot,
                    "type": "Practitioner"
                },
                "item": [
                    {
                        "linkId": question_id,
                        "answer": answer
                    }
                for question_id, answer in questions.items() if answer[0]["valueString"]]
            }

            try:
                canvas_id = self.fumage_helper.perform_create(payload)
                # self.perform_note_state_change(note_id)
                self.done_row(f"{row['ID']}|{patient}|{patient_key}|{canvas_id}")
                ids.add(row['ID'])
            except BaseException as e:
                self.error_row(f"{row['ID']}|{patient}|{patient_key}", e)
                continue

if __name__ == "__main__":
    loader = QuickNotesLoader(environment="ways2well")
    # loader.make_json_file()
    # loader.make_csv()
    valid_rows = loader.validate(delimiter=",")
    loader.load(valid_rows)
