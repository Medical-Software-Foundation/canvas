import arrow

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.questionnaire_result import CreateQuestionnaireResult
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.questionnaire import Questionnaire, Interview

from logger import log

class PHQWorkflow(BaseProtocol):
    """
    Return a CreateQuestionnaireResult effect in response to a committed Questionnaire Command that
    contains questions coded for either PHQ9 or PHQ2 questionnaire.

    Further return a Protocol Card Effect if a PHQ9 should be recommended based on the 
    PHQ2 score
    """

    RESPONDS_TO = [
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_ENTER_IN_ERROR)
    ]

    PHQ_CODE_SYSTEM = "LOINC"
    PHQ9_CODE = "44249-1"
    PHQ2_CODE = "58120-7"

    def score(self, interview):
        # count expected questions (excluding text-based questions) and validate all are answered
        questionnaire = interview.questionnaires.order_by('id').first()
        expected_questions = questionnaire.questions.exclude(response_option_set__type="TXT").count()
        answered_questions = interview.interview_responses.exclude(response_option__response_option_set__type="TXT")
        if answered_questions.count() != expected_questions:
            return None
        else:
            # sum up the numerical value of each answered questionnaire and exclude any free text response questions
            score = 0
            for response in answered_questions:
                score = score + int(response.response_option.value)

        return score

    def score_phq9(self):
        """Score the PHQ9 questionnaire"""

        score = self.score(self.interview)

        if score is None:
            abnormal = False
            narrative = (
                "Unable to score questionnaire due to missing questions"
            )
        elif score < 1:
            abnormal = False
            severity = "no"
            action = "No further actions"
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."
        elif score < 5:
            abnormal = False
            severity = "minimal"
            action = "No further actions"
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."
        elif score < 10:
            abnormal = True
            severity = "mild"
            action = "Consider watchful waiting and repeat PHQ-9 at follow up"
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."
        elif score < 15:
            abnormal = True
            severity = "moderate"
            action = "Consider treatment plan, counseling, follow up and/or pharmacotherapy"
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."
        elif score < 20:
            abnormal = True
            severity = "moderately severe"
            action = "Consider active treatment with pharmacotherapy and/or psychotherapy"
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."
        else:
            abnormal = True
            severity = "severe"
            action = (
                "Consider immediate initiation of pharmacotherapy and, if severe impairment or "
                "poor response to therapy, expedited referral to a mental health specialist for "
                "psychotherapy and/or collaborative management"
            )
            narrative = f"Score of {score} indicates {severity} depression symptoms. {action}."

        return score, CreateQuestionnaireResult(
            interview_id=str(self.interview.id),
            score=score,
            abnormal=abnormal,
            narrative=narrative,
            code_system=self.PHQ_CODE_SYSTEM,
            code="44261-6",
        )

    def score_phq2(self):
        """Score the PHQ2 questionnaire"""

        score = self.score(self.interview)

        if score is None:
            abnormal = False
            narrative = (
                "Unable to score questionnaire due to missing questions"
            )
        elif score > 2:
            abnormal = True
            narrative = (
                f"Positive screen with score of {score}. Recommend further assessment with PHQ-9."
            )
        else:
            abnormal = False
            narrative = f"Negative screen with score of {score}."

        return score, CreateQuestionnaireResult(
            interview_id=str(self.interview.id),
            score=score,
            abnormal=abnormal,
            narrative=narrative,
            code_system=self.PHQ_CODE_SYSTEM,
            code="55758-7",
        )

    def phq9_recommendation(self, score, interview):
        date = arrow.get(interview.created)
        if score and score > 2:
            self.protocol_card.narrative = f"Patient had positive PHQ-2 on {date.format('M/D/YYYY')}"

            phq9_found = Interview.objects.filter(
                **self.interview_filters,
                questionnaires__code=self.PHQ9_CODE,
                created__gte=date.shift(days=-30).isoformat()
            ).first()

            # no phq9 has been filled out in the last 30 days
            if not phq9_found:
                log.info("PHQ9 has NOT been filled out within the last 30 days, creating recommendation")
                phq9_questionnaire_id = Questionnaire.objects.get(
                    code=self.PHQ9_CODE,
                    can_originate_in_charting=True
                ).id
                phq9_command = QuestionnaireCommand(questionnaire_id=str(phq9_questionnaire_id))
                
                self.protocol_card.status = ProtocolCard.Status.DUE
                self.protocol_card.recommendations.append(phq9_command.recommend(
                    button="Interview",
                    title=f"Administer PHQ-9 before {date.shift(days=30).format('M/D/YYYY')}"
                ))
            else:
                log.info("PHQ9 has been filled out within the last 30 days")

    def confirm_phq9_recommendation(self):
        most_recent_phq2_found =  Interview.objects.filter(
            **self.interview_filters,
            questionnaires__code=self.PHQ2_CODE
        ).order_by('-id').first()

        if most_recent_phq2_found:
            score = self.score(most_recent_phq2_found)
            log.info(f"Most Recent Active PHQ-2 Questionnaire has a score of {score}")
            self.phq9_recommendation(score, most_recent_phq2_found)
        else:
            log.info("No PHQ2 found")


    def compute(self) -> list[Effect]:
        # Get the interview object, which will be the anchor object on the Questionnaire command.
        command = Command.objects.get(id=self.event.target.id)
        self.interview = command.anchor_object
        self.patient = self.interview.patient

        self.interview_filters = {
            "patient_id": self.patient.dbid,
            "deleted": False, 
            "entered_in_error_id__isnull": True,
            "committer_id__isnull": False
        }

        self.protocol_card = ProtocolCard(
            patient_id=self.patient.id,
            key="PHQ9_RECOMMENDATION",
            title="Recommend PHQ-9 for positive PHQ-2 screening",
            status=ProtocolCard.Status.SATISFIED
        )

        effects = []

        # Grab the questionnaire associated with the Questionnaire command to see if it is PHQ related 
        questionnaire = self.interview.questionnaires.order_by('id').first()
        if not questionnaire:
            return effects

        if questionnaire.code == self.PHQ9_CODE:
            if self.event.type == EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT:
                log.info(f"PHQ-9 Questionnaire has been committed")
                score, phq_9_result_effect = self.score_phq9()
                log.info(f"PHQ-9 Questionnaire has a score of {score} with narrative {phq_9_result_effect.narrative}")
                effects.append(phq_9_result_effect.apply())

                log.info(f"Mark PHQ9_RECOMMENDATION Protocol as satisfied")
                effects.append(self.protocol_card.apply())
            else:
                log.info(f"PHQ-9 Questionnaire has been EIE")
                # If a PHQ-9 is EIE, we need to make sure there isn't a PHQ-2 with a 
                # postive result
                self.confirm_phq9_recommendation()
                effects.append(self.protocol_card.apply())

        elif questionnaire.code == self.PHQ2_CODE:
            if self.event.type == EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT:
                log.info(f"PHQ-2 Questionnaire has been committed")
                score, phq_2_result_effect = self.score_phq2()
                log.info(f"PHQ-2 Questionnaire has a score of {score} with narrative {phq_2_result_effect.narrative}")
                effects.append(phq_2_result_effect.apply())

                # check to see if a postive phq2 should recomment a phq9 screen
                self.phq9_recommendation(score, self.interview)
                effects.append(self.protocol_card.apply())
            else:
                log.info(f"PHQ-2 Questionnaire has been EIE")
                # If a PHQ-2 is EIE, we need to find if this patient has any PHQ-2
                self.confirm_phq9_recommendation()
                effects.append(self.protocol_card.apply())

        return effects
