import csv

from data_migrations.utils import fetch_from_json, write_to_json
from data_migrations.charm_migration.utils import CharmPatientAPI
from data_migrations.template_migration.questionnaire_response import QuestionnaireResponseLoaderMixin

class QuestionnaireLoader(QuestionnaireResponseLoaderMixin):
    def __init__(self, environment) -> None:
        self.environment = environment
        self.patient_map_file = "PHI/patient_id_map.json"
        self.patient_map = fetch_from_json(self.patient_map_file)
        self.json_file = "PHI/questionnaires_patient.json"
        self.questionnaires_json_file = "PHI/questionnaire_info.json"
        self.questionnaire_questions_json_file = "PHI/questionnaire_questions.json"
        self.questionnaire_csv = "PHI/questionnaires.csv"


    def make_responses_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        patient_ids = self.patient_map.keys()
        charm_patient_api.fetch_questionnaire_answers(patient_ids, self.json_file)
        # because it is so large, the fetch_questionnaires method continually writes to the file

    def make_questionnaires_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        questionnaire_data = charm_patient_api.fetch_questionnaires()
        write_to_json(self.questionnaires_json_file, questionnaire_data)

    def make_questionnaire_questions_json(self):
        charm_patient_api = CharmPatientAPI(environment=self.environment)
        questionnaire_ids = [q["questionnaire_id"]  for q in fetch_from_json(self.questionnaires_json_file)]
        questionnaire_questions_data = charm_patient_api.fetch_questionnaire_questions(questionnaire_ids)
        write_to_json(self.questionnaire_questions_json_file, questionnaire_questions_data)

    def analyze_data(self):
        questionnaires_data = {}
        response_has_appointment_count = 0
        response_no_appointment_count = 0
        response_no_appointment_and_not_submitted = 0
        response_data = fetch_from_json(self.json_file)
        for patient_id, responses in response_data.items():
            for response in responses:
                if not response["appointment_id"]:
                    response_no_appointment_count += 1
                    if response["is_submitted"] == "false":
                        response_no_appointment_and_not_submitted += 1
                else:
                    response_has_appointment_count += 1
                questionnaire_id = response["questionnaire_id"]
                if questionnaire_id not in questionnaires_data:
                    questionnaires_data[questionnaire_id] = {
                        "name": response["questionnaire_name"],
                        "questions": {}
                    }
                for answer in response["questionnaire_with_answers"]["questions"]:
                    entry_id = answer["entry_id"]
                    if entry_id not in questionnaires_data[questionnaire_id]["questions"]:
                        questionnaires_data[questionnaire_id]["questions"][entry_id] = {
                            "notes": answer["notes"],
                            "options": "; ".join(answer.get("options", [])),
                            "is_multi_choice": answer["is_multi_choice"],
                            "is_mandatory": answer["is_mandatory"],
                            "is_deleted": answer["is_deleted"],
                            "position": answer["position"],
                            "notes_type": answer["notes_type"],

                        }
                    else:
                        assert answer["notes"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["notes"]
                        assert "; ".join(answer.get("options", [])) == questionnaires_data[questionnaire_id]["questions"][entry_id].get("options", [])
                        assert answer["is_multi_choice"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["is_multi_choice"]
                        assert answer["is_mandatory"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["is_mandatory"]
                        assert answer["is_deleted"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["is_deleted"]
                        assert answer["position"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["position"]
                        assert answer["notes_type"] == questionnaires_data[questionnaire_id]["questions"][entry_id]["notes_type"]
                        assert "; ".join(answer.get("options", [])) == questionnaires_data[questionnaire_id]["questions"][entry_id].get("options", [])


        with open(self.questionnaire_csv, "w") as fhandle:
            headers = [
                "questionnaire_id",
                "questionnaire_name",
                "question_entry_id",
                "notes",
                "options",
                "is_multi_choice",
                "is_mandatory",
                "is_deleted",
                "position",
                "notes_type",
            ]
            writer = csv.DictWriter(fhandle, fieldnames=headers)
            writer.writeheader()
            for q_id, q_data in questionnaires_data.items():
                questionnaire_name = q_data["name"]

                row_to_write = {
                    "questionnaire_id": q_id,
                    "questionnaire_name": questionnaire_name
                }

                for entry_id, qs in q_data["questions"].items():
                    row_to_write["question_entry_id"] = entry_id
                    row_to_write.update(qs)

                    writer.writerow(row_to_write)

        print(f"Successfully wrote to {self.questionnaire_csv}")

        print(f"Has appointment ref: {response_has_appointment_count}")
        print(f"No appointment ref: {response_no_appointment_count}")
        print(f"No appointment ref and not submitted: {response_no_appointment_and_not_submitted}")


if __name__ == "__main__":
    loader = QuestionnaireLoader("ways2well")
    # loader.make_responses_json()
    # loader.make_questionnaires_json()
    # loader.make_questionnaire_questions_json()
    loader.analyze_data()
