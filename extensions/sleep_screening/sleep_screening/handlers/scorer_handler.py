from datetime import date

from canvas_sdk.effects import Effect
from canvas_sdk.effects.questionnaire_result import CreateQuestionnaireResult
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command
from logger import log

from sleep_screening.patient_context import build_context
from sleep_screening.scoring.registry import get_scorer

# The three instruments have no LOINC codes (all copyrighted); scoring results
# use INTERNAL codes.
SCORE_CODE_SYSTEM = "INTERNAL"


class InstrumentScorer(BaseProtocol):
    """Scores one of our bundled sleep instruments when its questionnaire command
    commits, writing a structured CreateQuestionnaireResult.

    QUESTIONNAIRE_COMMAND__POST_COMMIT fires for every questionnaire in the
    instance, so the handler checks the committed questionnaire's code FIRST and
    returns immediately (before any patient-context or scoring work) when the
    questionnaire is not one of ours."""

    RESPONDS_TO = [EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)]

    def compute(self) -> list[Effect]:
        try:
            command = Command.objects.get(id=self.event.target.id)
        except Command.DoesNotExist:
            return []

        interview = command.anchor_object
        if interview is None:
            return []

        # Cheap gate first: is this one of our three instruments?
        questionnaire = interview.questionnaires.first()
        if questionnaire is None or not questionnaire.code:
            return []
        code = questionnaire.code
        scorer = get_scorer(code)
        if scorer is None:
            return []

        # Only now do the (more expensive) scoring work.
        responses = self._responses(interview)
        patient_id = str(interview.patient.id) if interview.patient else ""
        context = build_context(patient_id, date.today())
        result = scorer(responses, context)

        log.info(
            "sleep_screening: scored "
            + str(code)
            + " -> "
            + str(result.score)
            + " ("
            + str(result.band)
            + ")"
        )

        return [
            CreateQuestionnaireResult(
                interview_id=str(interview.id),
                score=float(result.score) if result.score is not None else 0.0,
                abnormal=result.abnormal,
                narrative=result.narrative,
                code_system=SCORE_CODE_SYSTEM,
                code=code + "_SCORE",
            ).apply()
        ]

    def _responses(self, interview) -> dict[str, float]:
        out = {}
        for resp in interview.interview_responses.all():
            option = resp.response_option
            question = resp.question
            if option is None or question is None:
                continue
            try:
                out[question.code] = float(option.value)
            except (ValueError, TypeError):
                continue
        return out
