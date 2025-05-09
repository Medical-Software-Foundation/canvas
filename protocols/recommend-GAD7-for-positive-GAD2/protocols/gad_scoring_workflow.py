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

class GADWorkflow(BaseProtocol):
    """
    Return a CreateQuestionnaireResult effect in response to a committed Questionnaire Command that
    contains questions coded for either GAD7 or GAD2 questionnaire.

    Further return a Protocol Card Effect if a GAD7 should be recommended based on the 
    GAD2 score
    """

    RESPONDS_TO = [
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_ENTER_IN_ERROR)
    ]

    GAD7_CODE_SYSTEM = "LOINC"
    GAD7_CODE = "69737-5"
    GAD2_CODE_SYSTEM = "SNOMED"
    GAD2_CODE = "836551000000102"

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

    def score_gad7(self):
        """Score the GAD7 questionnaire"""

        score = self.score(self.interview)

        if score is None:
            abnormal = False
            narrative = (
                "Unable to score questionnaire due to missing questions"
            )
        elif score < 5:
            abnormal = False
            severity = "no anxiety disorder"
            narrative = f"Score of {score} indicates {severity}."
        elif score < 8:
            abnormal = False
            severity = "mild anxiety symptoms"
            narrative = f"Score of {score} indicates {severity}."
        elif score < 10:
            abnormal = True
            severity = "mild anxiety symptoms, consider diagnosis of GAD"
            narrative = f"Score of {score} indicates {severity}."
        elif score < 15:
            abnormal = True
            severity = "moderate anxiety symptoms, consider diagnosis of GAD"
            narrative = f"Score of {score} indicates {severity}."
        else:
            abnormal = True
            severity = "severe anxiety symptoms, consider diagnosis of GAD"
            narrative = f"Score of {score} indicates {severity}."

        return score, CreateQuestionnaireResult(
            interview_id=str(self.interview.id),
            score=score,
            abnormal=abnormal,
            narrative=narrative,
            code_system=self.GAD7_CODE_SYSTEM,
            code="70274-6",
        )

    def score_gad2(self):
        """Score the GAD2 questionnaire"""

        score = self.score(self.interview)

        if score is None:
            abnormal = False
            narrative = (
                "Unable to score questionnaire due to missing questions"
            )
        elif score < 3:
            abnormal = False
            severity = "negative screen for anxiety disorder"
            narrative = f"Score of {score} indicates {severity}."
        else:
            abnormal = True
            severity = "positive screen, further diagnostic evaluation for GAD recommended"
            narrative = f"Score of {score} indicates {severity}."

        return score, CreateQuestionnaireResult(
            interview_id=str(self.interview.id),
            score=score,
            abnormal=abnormal,
            narrative=narrative,
            code_system="INTERNAL",
            code="gad2",
        )

    def gad7_recommendation(self, score, interview):
        date = arrow.get(interview.created)
        if score and score > 2:
            self.protocol_card.narrative = f"Patient had positive GAD-2 on {date.format('M/D/YYYY')}"

            gad7_found = Interview.objects.filter(
                **self.interview_filters,
                questionnaires__code=self.GAD7_CODE,
                created__gte=date.shift(days=-30).isoformat()
            ).first()

            # no gad7 has been filled out in the last 30 days
            if not gad7_found:
                log.info("GAD7 has NOT been filled out within the last 30 days, creating recommendation")
                gad7_questionnaire_id = Questionnaire.objects.get(
                    code=self.GAD7_CODE,
                    can_originate_in_charting=True
                ).id
                gad7_command = QuestionnaireCommand(questionnaire_id=str(gad7_questionnaire_id))
                
                self.protocol_card.status = ProtocolCard.Status.DUE
                self.protocol_card.recommendations.append(gad7_command.recommend(
                    button="Interview",
                    title=f"Administer GAD-7 before {date.shift(days=30).format('M/D/YYYY')}"
                ))
            else:
                log.info("GAD7 has been filled out within the last 30 days")

    def confirm_gad7_recommendation(self):
        most_recent_gad2_found =  Interview.objects.filter(
            **self.interview_filters,
            questionnaires__code=self.GAD2_CODE
        ).order_by('-id').first()

        if most_recent_gad2_found:
            score = self.score(most_recent_gad2_found)
            log.info(f"Most Recent Active GAD-2 Questionnaire has a score of {score}")
            self.gad7_recommendation(score, most_recent_gad2_found)
        else:
            log.info("No GAD2 found")


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
            key="GAD7_RECOMMENDATION",
            title="Recommend GAD-7 for positive GAD-2 screening",
            status=ProtocolCard.Status.SATISFIED
        )

        effects = []

        # Grab the questionnaire associated with the Questionnaire command to see if it is GAD related 
        questionnaire = self.interview.questionnaires.order_by('id').first()
        if not questionnaire:
            return effects

        if questionnaire.code == self.GAD7_CODE:
            if self.event.type == EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT:
                log.info(f"GAD-7 Questionnaire has been committed")
                score, gad_7_result_effect = self.score_gad7()
                log.info(f"GAD-7 Questionnaire has a score of {score} with narrative {gad_7_result_effect.narrative}")
                effects.append(gad_7_result_effect.apply())

                log.info(f"Mark GAD7_RECOMMENDATION Protocol as satisfied")
                effects.append(self.protocol_card.apply())
            else:
                log.info(f"GAD-7 Questionnaire has been EIE")
                # If a GAD-7 is EIE, we need to make sure there isn't a GAD-2 with a 
                # postive result
                self.confirm_gad7_recommendation()
                effects.append(self.protocol_card.apply())

        elif questionnaire.code == self.GAD2_CODE:
            if self.event.type == EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT:
                log.info(f"GAD-2 Questionnaire has been committed")
                score, gad_2_result_effect = self.score_gad2()
                log.info(f"GAD-2 Questionnaire has a score of {score} with narrative {gad_2_result_effect.narrative}")
                effects.append(gad_2_result_effect.apply())

                # check to see if a postive gad2 should recomment a gad7 screen
                self.gad7_recommendation(score, self.interview)
                effects.append(self.protocol_card.apply())
            else:
                log.info(f"GAD-2 Questionnaire has been EIE")
                # If a GAD-2 is EIE, we need to find if this patient has any GAD-2
                self.confirm_gad7_recommendation()
                effects.append(self.protocol_card.apply())

        return effects
