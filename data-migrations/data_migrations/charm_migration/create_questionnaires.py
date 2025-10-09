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


    def edge_case_examples(self):
        headers = [
            "Patient ID",
            "Example Type",
            "Questionnaire ID",
            "Questionnaire Name",
            "Questionnaire Type",
            "Questionnaire Map ID",
            "Last Modified",
            "Appointment ID",
            "Question Entry ID",
            "Notes",
            "Options",
            "Is Multi Choice",
            "Is Mandatory",
            "Is Deleted",
            "Position",
            "Notes Type",
            "Answer",
        ]
        example_data = []
        response_data = fetch_from_json(self.json_file)

        no_appt = False
        has_appt = False
        missing_date = False
        submitted_1 = False
        submitted_2 = False
        submitted_3 = False
        submitted_4 = False
        answer_deleted = False
        answer_not_in_options = False

        for patient_id, responses in response_data.items():
            for response in responses:
                if not response["appointment_id"] and not no_appt:
                    example_data.append((patient_id, "No appointment ID associated to the response", response,))
                    no_appt = True
                    continue
                elif response["appointment_id"] and not has_appt:
                    example_data.append((patient_id, "Has an appointment ID associated to the response", response,))
                    has_appt = True
                    continue
                if not response["last_modified_time"] and not missing_date:
                    example_data.append((patient_id, "Missing a last modified date", response,))
                    missing_date = True
                    continue

                if response["is_submitted"] == "false" and response["is_saved"] == "false" and not submitted_1:
                    example_data.append((patient_id, "Both is_submitted and is_saved are false", response,))
                    submitted_1 = True
                elif response["is_submitted"] == "true" and response["is_saved"] == "false" and not submitted_2:
                    example_data.append((patient_id, "is_submitted is true and is_saved is false", response,))
                    submitted_2 = True
                elif response["is_submitted"] == "false" and response["is_saved"] == "true" and not submitted_3:
                    example_data.append((patient_id, "is_submitted is false and is_saved is true", response,))
                    submitted_3 = True
                elif response["is_submitted"] == "true" and response["is_saved"] == "true" and not submitted_4:
                    example_data.append((patient_id, "Both is_submitted and is_saved are true", response,))
                    submitted_4 = True

                for answer in response["questionnaire_with_answers"]["questions"]:
                    if answer["is_deleted"] is True and not answer_deleted:
                        example_data.append((patient_id, "Answer given in questionnaire response has is_deleted=true", response,))
                        answer_deleted = True
                        break
                    if answer.get("options") and answer.get("answer") and answer["answer"] not in answer["options"] and not answer_not_in_options:
                        example_data.append((patient_id, "Answer given in questionnaire response is not included in question options", response,))
                        answer_not_in_options = True
                        break

        with open("PHI/example_data.csv", "w") as fhandle:
            writer = csv.DictWriter(fhandle, fieldnames=headers, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for example in example_data:
                row_to_write = {
                    "Patient ID": example[0],
                    "Example Type": example[1],
                    "Questionnaire ID": example[2]["questionnaire_id"],
                    "Questionnaire Name": example[2]["questionnaire_name"],
                    "Questionnaire Type": example[2]["questionnaire_with_answers"]["questionnaire_type"],
                    "Questionnaire Map ID": example[2]["ques_map_id"],
                    "Last Modified": example[2]["last_modified_time"],
                    "Appointment ID": example[2]["appointment_id"]
                }
                for answer in example[2]["questionnaire_with_answers"]["questions"]:
                    entry_id = answer["entry_id"]
                    row_to_write["Question Entry ID"] = entry_id
                    row_to_write["Notes"] = answer["notes"]
                    row_to_write["Options"] = "; ".join(answer.get("options", []))
                    row_to_write["Is Multi Choice"] = answer["is_multi_choice"]
                    row_to_write["Is Mandatory"] = answer["is_mandatory"]
                    row_to_write["Is Deleted"] = answer["is_deleted"]
                    row_to_write["Position"] = answer["position"]
                    row_to_write["Notes Type"] = answer["notes_type"]
                    row_to_write["Answer"] = answer.get("answer", "")

                    writer.writerow(row_to_write)


if __name__ == "__main__":
    loader = QuestionnaireLoader("ways2well")
    # loader.make_responses_json()
    # loader.make_questionnaires_json()
    # loader.make_questionnaire_questions_json()
    # loader.analyze_data()
    loader.edge_case_examples()
