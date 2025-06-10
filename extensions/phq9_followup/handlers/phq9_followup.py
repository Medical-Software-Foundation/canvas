from uuid import uuid4

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.questionnaire import Questionnaire, Interview, InterviewQuestionResponse

from canvas_sdk.commands.commands.questionnaire import QuestionnaireCommand
from canvas_sdk.commands.commands.questionnaire.question import ResponseOption

PHQ_CODE_SYSTEM = "LOINC"
PHQ9_CODE = "44249-1"
PHQ2_CODE = "58120-7"


class PHQ9Followup(BaseHandler):

    RESPONDS_TO = [
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)
    ]

    def compute(self) -> list[Effect]:
        # See if the committed questionnaire command is a PHQ-2
        event_command = Command.objects.get(id=self.event.target.id)
        committed_questionnaire_is_phq2 = Questionnaire.objects.filter(
            dbid=event_command.data['questionnaire']['value'],
            code_system=PHQ_CODE_SYSTEM,
            code=PHQ2_CODE
        ).exists()

        # If this was a different questionnaire, we can exit early
        if not committed_questionnaire_is_phq2:
            return []

        # Check the score of this PHQ-2
        phq_2_interview = event_command.anchor_object
        score = self.score(phq_2_interview)
        if score and score <= 2:
            # If the score is not abnormal, no PHQ-9 needed
            return []

        # Prep a new questionnaire command, selecting the PHQ-9
        phq_9 = Questionnaire.objects.filter(can_originate_in_charting=True, code_system=PHQ_CODE_SYSTEM, code=PHQ9_CODE).first()
        new_command = QuestionnaireCommand(
            note_uuid=str(event_command.note.id),
            questionnaire_id=str(phq_9.id),
            command_uuid=str(uuid4()),
        )

        # Pull forward overlapping responses from the PHQ-2
        for new_question in new_command.questions:
            # Get the response to this PHQ-9 question from the PHQ-2
            # interview, if it exists.
            previous_phq_2_response = InterviewQuestionResponse.objects.filter(
                interview=phq_2_interview,
                question__code_system=new_question.coding['system'],
                question__code=new_question.coding['code'],
            ).first()
            if previous_phq_2_response:
                # Find the equivalent PHQ-9 response option
                for option in new_question.options:
                    if option.code == previous_phq_2_response.response_option.code:
                        new_question.add_response(option=option)

        # Originate the command and immediately update it with the filled out
        # responses (if any)
        return [new_command.originate(), new_command.edit()]

    def score(self, interview):
        # Count expected questions (excluding text-based questions) and validate
        # all are answered
        questionnaire = interview.questionnaires.order_by('id').first()
        expected_questions = questionnaire.questions.exclude(response_option_set__type="TXT").count()
        answered_questions = interview.interview_responses.exclude(response_option__response_option_set__type="TXT")
        if answered_questions.count() != expected_questions:
            return None
        else:
            # Sum up the numerical value of each answered questionnaire and
            # exclude any free text response questions
            score = 0
            for response in answered_questions:
                score = score + int(response.response_option.value)
        return score
