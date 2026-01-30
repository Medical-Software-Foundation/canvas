from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from logger import log


class RequireAllQuestionsAnsweredHandler(BaseHandler):
    """Prevents committing a questionnaire unless all questions are answered."""

    RESPONDS_TO = EventType.Name(EventType.QUESTIONNAIRE_COMMAND__PRE_COMMIT)

    def compute(self) -> list[Effect]:
        """Block questionnaire commit if any questions are unanswered."""
        command_id = self.event.target.id

        log.info(f"[RequireAllQuestionsAnsweredHandler] Validating questionnaire command {command_id}")

        # Get the command and its associated interview
        command = Command.objects.get(id=command_id)
        interview = command.data_object

        if not interview:
            log.warning(f"[RequireAllQuestionsAnsweredHandler] No interview found for command {command_id}")
            return []

        # Get the questionnaire and its questions
        questionnaire = interview.questionnaires.first()
        if not questionnaire:
            log.warning(f"[RequireAllQuestionsAnsweredHandler] No questionnaire found for interview")
            return []

        # Get all questions and responses
        all_questions = set(questionnaire.questions.values_list("id", flat=True))
        answered_questions = set(
            interview.interview_responses.values_list("question_id", flat=True)
        )

        # Find unanswered questions
        unanswered_questions = all_questions - answered_questions

        if unanswered_questions:
            unanswered_count = len(unanswered_questions)
            total_count = len(all_questions)

            # Get the names of unanswered questions for the error message
            unanswered_names = list(
                questionnaire.questions.filter(id__in=unanswered_questions).values_list("name", flat=True)
            )

            log.info(
                f"[RequireAllQuestionsAnsweredHandler] Blocking commit - "
                f"{unanswered_count}/{total_count} questions unanswered for command {command_id}"
            )

            validation_error = CommandValidationErrorEffect()
            if unanswered_count <= 3:
                questions_display = ", ".join(unanswered_names)
                validation_error.add_error(
                    f"Cannot commit questionnaire: {unanswered_count} question(s) unanswered. "
                    f"Please answer: {questions_display}"
                )
            else:
                validation_error.add_error(
                    f"Cannot commit questionnaire: {unanswered_count} of {total_count} questions unanswered. "
                    f"Please answer all questions before committing."
                )
            return [validation_error.apply()]

        log.info(f"[RequireAllQuestionsAnsweredHandler] All questions answered, allowing commit for command {command_id}")
        return []
