from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.questionnaire_result import CreateQuestionnaireResult
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data import Questionnaire
from canvas_sdk.v1.data.command import Command
from logger import log


class Protocol(BaseProtocol):
    """
    Automates depression screening workflow:
    1. When PHQ-9 is committed with score ≤ 20, automatically originate a MADRS questionnaire
    2. When MADRS is committed, add questionnaire result with score interpretation to Social Determinants section
    """

    RESPONDS_TO = [EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)]

    # Questionnaire identifiers
    PHQ9_NAME = "PHQ-9"
    MADRS_NAME = "MADRS"
    MADRS_EXACT_NAME = "MADRS - Depression Screening"

    # PHQ-9 threshold for triggering MADRS
    PHQ9_SCORE_THRESHOLD = 20

    # MADRS scoring scale (standard interpretation)
    MADRS_RANGES = [
        (0, 6, "Normal/No depression"),
        (7, 19, "Mild depression"),
        (20, 34, "Moderate depression"),
        (35, 60, "Severe depression"),
    ]

    # Score threshold for abnormal flag
    MADRS_ABNORMAL_THRESHOLD = 7

    def compute(self) -> list[Effect]:
        """Handle questionnaire commit events for PHQ-9 and MADRS."""
        # Get the command and interview from the event
        command = Command.objects.get(id=self.event.target.id)
        interview = command.anchor_object

        # Skip if interview is not committed
        if not interview.committer:
            return []

        note_uuid = self.event.context["note"]["uuid"]

        # Get all questionnaires associated with this interview
        questionnaires = interview.questionnaires.all()

        # Check if this is a PHQ-9
        phq9_questionnaire = self._find_questionnaire_by_name(questionnaires, self.PHQ9_NAME)
        if phq9_questionnaire:
            return self._handle_phq9_commit(interview, note_uuid)

        # Check if this is a MADRS
        madrs_questionnaire = self._find_questionnaire_by_name(questionnaires, self.MADRS_NAME)
        if madrs_questionnaire:
            return self._handle_madrs_commit(interview, note_uuid)

        return []

    def _find_questionnaire_by_name(self, questionnaires, name: str):
        """
        Find a questionnaire by name with strict matching to avoid false positives.
        Checks if the name starts with the search term to avoid substring matches.
        """
        name_upper = name.upper()
        for q in questionnaires:
            if q.name:
                q_name_upper = q.name.upper()
                # Check if name starts with the search term (e.g., "PHQ-9" or "MADRS")
                # This avoids matching "PHQ-9" in "MADRS (PHQ-9 Workflow)"
                if q_name_upper.startswith(name_upper):
                    return q
        return None

    def _calculate_score(self, interview) -> int:
        """Calculate the total score from interview responses."""
        score = 0
        for response in interview.interview_responses.select_related('response_option').all():
            try:
                if response.response_option and response.response_option.value:
                    score += int(response.response_option.value)
            except (ValueError, TypeError):
                log.warning(f"Could not parse response value: {response.response_option.value}")
        return score

    def _handle_phq9_commit(self, interview, note_uuid: str) -> list[Effect]:
        """Handle PHQ-9 commit: originate MADRS if score ≤ threshold."""
        score = self._calculate_score(interview)
        log.info(f"PHQ-9 committed with score: {score}")

        if score > self.PHQ9_SCORE_THRESHOLD:
            log.info(f"PHQ-9 score > {self.PHQ9_SCORE_THRESHOLD}, not originating MADRS")
            return []

        # Find MADRS questionnaire by internal code system to get the custom instance questionnaire
        # This avoids finding auto-provisioned system questionnaires that aren't visible in the UI
        madrs = Questionnaire.objects.filter(
            code_system="internal",
            code=self.MADRS_NAME
        ).first()

        # Fallback: search by name, excluding versioned external questionnaires
        if not madrs:
            log.warning("No MADRS found with code_system='internal', falling back to name search")
            all_madrs = Questionnaire.objects.filter(name__icontains=self.MADRS_NAME).all()

            # Use the first one that doesn't have "(v" in the name (to avoid versioned external ones)
            for q in all_madrs:
                if "(v" not in q.name.lower():
                    madrs = q
                    break

            # If still no match, use first one
            if not madrs and all_madrs:
                madrs = all_madrs[0]

        if not madrs:
            log.error("MADRS questionnaire not found in the system. Please ensure a MADRS questionnaire is installed.")
            return []

        log.info(f"Originating MADRS questionnaire (ID: {madrs.id}, Name: {madrs.name}) for PHQ-9 score {score}")

        # Originate the MADRS questionnaire
        madrs_command = QuestionnaireCommand(
            note_uuid=note_uuid,
            questionnaire_id=str(madrs.id)
        )

        return [madrs_command.originate()]

    def _handle_madrs_commit(self, interview, note_uuid: str) -> list[Effect]:
        """Handle MADRS commit: add questionnaire result with score interpretation."""
        score = self._calculate_score(interview)
        interpretation = self._interpret_madrs_score(score)

        narrative = f"Score of {score} indicates {interpretation.lower()}"
        log.info(f"Adding MADRS result: {narrative}")

        # Determine if result is abnormal (score >= threshold indicates at least mild depression)
        abnormal = score >= self.MADRS_ABNORMAL_THRESHOLD

        # Create a questionnaire result in the Social Determinants section
        # Note: Removed code_system and code parameters to avoid auto-provisioning external questionnaires
        result = CreateQuestionnaireResult(
            interview_id=str(interview.id),
            score=float(score),
            abnormal=abnormal,
            narrative=narrative
        )

        return [result.apply()]

    def _interpret_madrs_score(self, score: int) -> str:
        """Interpret MADRS score based on standard ranges."""
        for min_score, max_score, interpretation in self.MADRS_RANGES:
            if min_score <= score <= max_score:
                return interpretation
        return f"Score out of range (expected 0-60, got {score})"
