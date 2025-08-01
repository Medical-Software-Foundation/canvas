from canvas_sdk.effects import Effect
from canvas_sdk.effects.questionnaire_result import CreateQuestionnaireResult
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command

from logger import log


class PrapareQuestionnaireResult(BaseProtocol):
    """
    Return a CreateQuestionnaireResult effect in response to a committed Questionnaire Command that
    contains questions coded for the PRAPARE questionnaire.
    """

    RESPONDS_TO = [EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)]

    # codes used to identify the questionnaire and its results
    QUESTIONNAIRE_CODE_SYSTEM = "LOINC"
    QUESTIONNAIRE_CODE = "93025-5"
    SCORE_CODE_SYSTEM = "INTERNAL"
    SCORE_CODE = "PREPARE"
    # if False, requires all non-text questions to be answered for scoring
    ALLOW_SKIPPED_QUESTIONS = False

    def score_results(self, score: int) -> tuple[bool, int]:
        # define the logic for scoring and narative of the questionnaire
        return False, f"Score of {score}"

    def compute(self) -> list[Effect]:
        # get the interview object, which will be the anchor object on the Questionnaire command.
        command = Command.objects.get(id=self.event.target.id)
        interview = command.anchor_object

        # return no effects if the interview has no questions related to the questionnaire
        questionnaire = interview.questionnaires.first()
        log.info(f"Questionnaire {questionnaire.name} committed with code {questionnaire.code} and system {questionnaire.code_system}")
        if not (questionnaire.code == self.QUESTIONNAIRE_CODE and questionnaire.code_system == self.QUESTIONNAIRE_CODE_SYSTEM):
            log.info(f"Questionnaire is not for {self.QUESTIONNAIRE_CODE} skipping...")
            return []

        # count expected questions (excluding text-based questions) and validate all are answered
        expected_questions = questionnaire.questions.exclude(response_option_set__type="TXT").count()
        answered_questions = interview.interview_responses.exclude(response_option__response_option_set__type="TXT")
        if not self.ALLOW_SKIPPED_QUESTIONS and answered_questions.count() != expected_questions:
            abnormal = False
            score = None
            narrative = (
                "Unable to score questionnaire due to missing questions"
            )
        else:
            # sum up the numerical value of each answered questionnaire and exclude any free text response questions
            score = 0
            for response in answered_questions:
                score = score + int(response.response_option.value)

            # determine the narrative and whether the result is abnormal
            abnormal, narrative = self.score_results(score)

        log.info(f"Questionnaire Scoring completed with {narrative}")
        # create and return the effect
        effect = CreateQuestionnaireResult(
            interview_id=str(interview.id),
            score=score,
            abnormal=abnormal,
            narrative=narrative,
            code_system=self.SCORE_CODE_SYSTEM,
            code=self.SCORE_CODE,
        )

        return [effect.apply()]
