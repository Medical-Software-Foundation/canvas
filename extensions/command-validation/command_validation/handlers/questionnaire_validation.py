from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from logger import log


class RequireAllQuestionsAnsweredHandler(BaseHandler):
    """Prevents committing a questionnaire unless all questions are answered."""

    RESPONDS_TO = EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_VALIDATION)

    def compute(self) -> list[Effect]:
        """Block questionnaire commit if any questions are unanswered."""
        command_id = self.event.target.id

        log.info(f"[RequireAllQuestionsAnsweredHandler] Validating questionnaire command {command_id}")

        command = Command.objects.get(id=command_id)
        data = command.data

        if not data:
            log.warning(f"[RequireAllQuestionsAnsweredHandler] No data found for command {command_id}")
            return []

        # Get questionnaire questions from the data
        questionnaire_info = data.get("questionnaire", {})
        extra = questionnaire_info.get("extra", {})
        questions = extra.get("questions", [])

        if not questions:
            log.warning(f"[RequireAllQuestionsAnsweredHandler] No questions found in questionnaire")
            return []

        # Check which questions are unanswered
        unanswered = []
        for question in questions:
            question_name = question.get("name")
            question_label = question.get("label", question_name)
            question_type = question.get("type")

            response = data.get(question_name)

            # Check if the question is answered based on its type
            if not self._is_answered(response, question_type):
                unanswered.append(question_label)

        if unanswered:
            unanswered_count = len(unanswered)
            total_count = len(questions)

            log.info(
                f"[RequireAllQuestionsAnsweredHandler] Blocking commit - "
                f"{unanswered_count}/{total_count} questions unanswered for command {command_id}"
            )

            validation_error = CommandValidationErrorEffect()
            if unanswered_count <= 3:
                questions_display = ", ".join(unanswered)
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

    def _is_answered(self, response, question_type: str) -> bool:
        """Check if a question response is considered answered."""
        if response is None:
            return False

        # For single choice (SING), response is an integer (pk of selected option)
        if question_type == "SING":
            return isinstance(response, int)

        # For multiple choice (MULT), response is a list - check if any option is selected
        if question_type == "MULT":
            if not isinstance(response, list):
                return False
            return any(opt.get("selected", False) for opt in response)

        # For text (TXT), response is a string - check if not empty
        if question_type == "TXT":
            return isinstance(response, str) and response.strip() != ""

        # For unknown types, consider answered if response exists
        return True
