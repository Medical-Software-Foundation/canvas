import json
import uuid
from http import HTTPStatus

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Questionnaire
from canvas_sdk.v1.data.note import Note


# Constants for response code mappings - must match questionnaire YAML exactly
GENERAL_HEALTH_LABELS = {
    "HRA_GENERAL_HEALTH_POOR": ("Poor", "poor"),
    "HRA_GENERAL_HEALTH_FAIR": ("Fair", "fair"),
    "HRA_GENERAL_HEALTH_GOOD": ("Good", "good"),
    "HRA_GENERAL_HEALTH_VERY_GOOD": ("Very good", "very-good"),
    "HRA_GENERAL_HEALTH_EXCELLENT": ("Excellent", "excellent"),
}

DIFFICULTY_LEVELS = {
    "NONE": ("No Difficulty", "none"),
    "LITTLE": ("A Little Difficulty", "little"),
    "SOME": ("Some Difficulty", "some"),
    "LOT": ("A Lot of Difficulty", "lot"),
    "UNABLE": ("Unable to Do", "unable"),
}

PHYSICAL_ACTIVITIES = [
    ("HRA_DIFF_STOOPING", "Stooping, crouching, or kneeling"),
    ("HRA_DIFF_LIFTING", "Lifting or carrying 10 lbs"),
    ("HRA_DIFF_REACHING", "Reaching above shoulder level"),
    ("HRA_DIFF_WRITING", "Writing or grasping small objects"),
    ("HRA_DIFF_WALKING_QUARTER", "Walking a quarter mile"),
    ("HRA_DIFF_HOUSEWORK", "Heavy housework"),
]

ADL_ACTIVITIES = [
    ("HRA_ADL_SHOPPING", "Shopping for personal items"),
    ("HRA_ADL_MONEY", "Managing money"),
    ("HRA_ADL_WALKING", "Walking across the room"),
    ("HRA_ADL_LIGHT_HOUSEWORK", "Light housework"),
    ("HRA_ADL_BATHING", "Bathing or showering"),
]


def _get_general_health_context(responses: dict) -> tuple[str, str]:
    """Extract general health label and CSS class from responses."""
    health_code = responses.get("HRA_GENERAL_HEALTH", "")
    if health_code in GENERAL_HEALTH_LABELS:
        return GENERAL_HEALTH_LABELS[health_code]
    return ("Not Specified", "good")


def _get_difficulty_level(response_code: str, question_code: str) -> tuple[str, str]:
    """Extract difficulty level from a response code."""
    if not response_code:
        return ("N/A", "none")

    # Extract the level suffix (e.g., "HRA_DIFF_STOOPING_NONE" -> "NONE")
    suffix = response_code.replace(f"{question_code}_", "")
    if suffix in DIFFICULTY_LEVELS:
        return DIFFICULTY_LEVELS[suffix]
    return ("N/A", "none")


def _get_physical_activities_context(responses: dict) -> list[dict]:
    """Build physical activities context for template."""
    activities = []
    for code, label in PHYSICAL_ACTIVITIES:
        response = responses.get(code, "")
        level_label, level_class = _get_difficulty_level(response, code)
        activities.append({
            "label": label,
            "level": level_label,
            "level_class": level_class,
        })
    return activities


def _get_help_text(help_response: str) -> str:
    """Extract help text from a help response code."""
    if help_response.endswith("_YES"):
        return "Yes"
    elif help_response.endswith("_NO"):
        return "No"
    elif help_response.endswith("_NA"):
        return "N/A"
    return "N/A"


def _get_adl_context(responses: dict) -> list[dict]:
    """Build ADL/IADL context for template - includes primary and follow-up questions."""
    adl_items = []
    for code, label in ADL_ACTIVITIES:
        response = responses.get(code, "")

        # Determine status based on primary response (Yes/No/Don't Know)
        # Follow-up questions differ based on primary response:
        # - "Yes" → "Do you receive help" (from {CODE}_HELP)
        # - "Don't Know" → "Due to your health?" (from {CODE}_HEALTH)
        # - "No" → No follow-up
        if response.endswith("_NO"):
            status_class = "no-difficulty"
            response_text = "No"
            followup_text = ""
            followup_type = None  # No follow-up for "No"
        elif response.endswith("_YES"):
            status_class = "has-difficulty"
            response_text = "Yes"
            # For "Yes" responses, check the _HELP follow-up
            help_code = f"{code}_HELP"
            help_response = responses.get(help_code, "")
            followup_text = _get_help_text(help_response)
            followup_type = "help"  # "Do you receive help"
        elif response.endswith("_DK"):
            status_class = "uncertain"
            response_text = "Don't Know"
            # For "Don't Know" responses, check the _HEALTH follow-up
            health_code = f"{code}_HEALTH"
            health_response = responses.get(health_code, "")
            followup_text = _get_help_text(health_response)
            followup_type = "health"  # "Due to your health?"
        else:
            # Not answered
            status_class = "no-difficulty"
            response_text = "N/A"
            followup_text = ""
            followup_type = None

        # Only show follow-up if we have a type and a valid answer (not N/A)
        show_followup = followup_type is not None and followup_text not in ("", "N/A")

        adl_items.append({
            "label": label,
            "status_class": status_class,
            "response_text": response_text,
            "help_text": followup_text,  # Keep key name for template compatibility
            "show_followup": show_followup,
            "followup_type": followup_type,
        })
    return adl_items


class SubmitHealthRiskAssessment(StaffSessionAuthMixin, SimpleAPI):
    """API endpoint to receive and process Health Risk Assessment form submissions."""

    BASE_PATH = "/plugin-io/api/health_risk_assessment"
    PREFIX = ""

    QUESTIONNAIRE_CODE = "HRA_AWV"
    QUESTIONNAIRE_CODE_SYSTEM = "INTERNAL"
    CUSTOM_COMMAND_SCHEMA_KEY = "healthRiskAssessmentSummary"

    # Output mode options
    OUTPUT_MODE_QUESTIONNAIRE = "questionnaire"
    OUTPUT_MODE_CUSTOM = "custom"
    OUTPUT_MODE_BOTH = "both"
    DEFAULT_OUTPUT_MODE = OUTPUT_MODE_CUSTOM

    def _get_output_mode(self) -> str:
        """Get the output mode from plugin secrets."""
        raw_mode = self.secrets.get("OUTPUT_MODE", self.DEFAULT_OUTPUT_MODE)
        mode: str = str(raw_mode).lower().strip()
        if mode not in (self.OUTPUT_MODE_QUESTIONNAIRE, self.OUTPUT_MODE_CUSTOM, self.OUTPUT_MODE_BOTH):
            return self.DEFAULT_OUTPUT_MODE
        return mode

    def _create_questionnaire_effects(
        self, note_uuid: str, responses: dict, questionnaire: Questionnaire
    ) -> tuple[list[Effect], str]:
        """Create questionnaire command effects. Returns (effects, command_uuid)."""
        command_uuid = str(uuid.uuid4())
        command = QuestionnaireCommand(
            note_uuid=note_uuid,
            command_uuid=command_uuid,
            questionnaire_id=str(questionnaire.id),
        )

        # Get questions and set responses
        questions = command.questions

        for question in questions or []:
            # Get question code from coding dict
            q_coding = getattr(question, 'coding', {}) or {}
            q_code = q_coding.get("code") if isinstance(q_coding, dict) else None
            if not q_code:
                q_code = getattr(question, 'code', None)

            response_value = responses.get(q_code) if q_code else None

            if response_value:
                options = getattr(question, 'options', None) or []
                for option in options:
                    opt_coding = getattr(option, 'coding', {}) or {}
                    opt_code = opt_coding.get("code") if isinstance(opt_coding, dict) else None
                    opt_code_attr = getattr(option, 'code', None)

                    if opt_code == response_value or opt_code_attr == response_value:
                        question.add_response(option=option)
                        break

        # Build result summary
        general_health = responses.get("HRA_GENERAL_HEALTH", "")
        if general_health:
            health_label = general_health.replace("HRA_GENERAL_HEALTH_", "").replace("_", " ").title()
            command.result = f"General Health: {health_label}"
        else:
            command.result = "Health Risk Assessment completed"

        return [command.originate(), command.edit(), command.commit()], command_uuid

    def _create_custom_command_effects(self, note_uuid: str, responses: dict) -> tuple[list[Effect], str]:
        """Create custom command effects with HTML summary. Returns (effects, command_uuid)."""
        # Build template context
        general_health_label, general_health_class = _get_general_health_context(responses)
        physical_activities = _get_physical_activities_context(responses)
        adl_items = _get_adl_context(responses)

        template_context = {
            "general_health_label": general_health_label,
            "general_health_class": general_health_class,
            "physical_activities": physical_activities,
            "adl_items": adl_items,
        }

        # Render templates
        content = render_to_string("templates/hra_summary.html", template_context)
        print_content = render_to_string("templates/hra_summary_print.html", template_context)

        # Create custom command
        command_uuid = str(uuid.uuid4())
        custom_command = CustomCommand(
            schema_key=self.CUSTOM_COMMAND_SCHEMA_KEY,
            content=content,
            print_content=print_content,
        )
        custom_command.command_uuid = command_uuid
        custom_command.note_uuid = note_uuid

        # CustomCommand only needs originate() - it's read-only and doesn't support commit()
        return [custom_command.originate()], command_uuid

    @api.post("/submit-hra")
    def submit_hra(self) -> list[Response | Effect]:
        """Process the submitted Health Risk Assessment form."""
        try:
            # Parse the form data
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8")

            form_data = json.loads(body)
            note_dbid = form_data.get("note_id")
            responses = form_data.get("responses", {})

            if not note_dbid:
                return [
                    JSONResponse(
                        {"success": False, "error": "Missing note_id"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

            # Convert note dbid to UUID
            note = Note.objects.filter(dbid=note_dbid).first()
            if not note:
                return [
                    JSONResponse(
                        {"success": False, "error": f"Note not found for id: {note_dbid}"},
                        status_code=HTTPStatus.NOT_FOUND,
                    )
                ]
            note_uuid = str(note.id)

            # Get output mode from secrets
            output_mode = self._get_output_mode()

            effects: list[Response | Effect] = []
            command_uuids: list[str] = []

            # Create questionnaire command if needed
            if output_mode in (self.OUTPUT_MODE_QUESTIONNAIRE, self.OUTPUT_MODE_BOTH):
                # Get the ACTIVE questionnaire
                questionnaire = Questionnaire.objects.filter(
                    code=self.QUESTIONNAIRE_CODE,
                    code_system=self.QUESTIONNAIRE_CODE_SYSTEM,
                    status="AC",
                ).first()

                if not questionnaire:
                    return [
                        JSONResponse(
                            {"success": False, "error": "Questionnaire not found"},
                            status_code=HTTPStatus.NOT_FOUND,
                        )
                    ]

                q_effects, q_uuid = self._create_questionnaire_effects(note_uuid, responses, questionnaire)
                effects.extend(q_effects)
                command_uuids.append(q_uuid)

            # Create custom command if needed
            if output_mode in (self.OUTPUT_MODE_CUSTOM, self.OUTPUT_MODE_BOTH):
                c_effects, c_uuid = self._create_custom_command_effects(note_uuid, responses)
                effects.extend(c_effects)
                command_uuids.append(c_uuid)

            # Add success response
            effects.append(
                JSONResponse({
                    "success": True,
                    "command_uuids": command_uuids,
                    "output_mode": output_mode,
                })
            )

            return effects

        except json.JSONDecodeError:
            return [
                JSONResponse(
                    {"success": False, "error": "Invalid JSON data"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        except Exception as e:
            return [
                JSONResponse(
                    {"success": False, "error": str(e)},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
