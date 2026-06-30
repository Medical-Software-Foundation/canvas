"""Resolve, introspect, and populate Canvas questionnaire / SA / exam commands.

Everything keys off the stable questionnaire ``code`` and resolves to the current
``questionnaire_id`` at runtime, so versioning (which changes the id, never the
code) never breaks a configured template.
"""

from uuid import uuid4

from canvas_sdk.commands.commands.questionnaire import QuestionnaireCommand
from canvas_sdk.commands.commands.questionnaire.question import ResponseOption
from canvas_sdk.v1.data import Questionnaire
from logger import log


def list_questionnaires() -> list[dict]:
    """Active, chart-originatable questionnaires/SAs/exams for the admin picker."""
    out: list[dict] = []
    try:
        rows = Questionnaire.objects.filter(
            status="AC", can_originate_in_charting=True
        ).values("name", "code", "code_system", "use_case_in_charting")
        for r in rows:
            out.append(
                {
                    "name": r.get("name", ""),
                    "code": r.get("code", ""),
                    "code_system": r.get("code_system", ""),
                    "use_case": r.get("use_case_in_charting", ""),
                }
            )
    except (AttributeError, ValueError) as exc:
        log.warning(f"questionnaire list failed: {exc}")
    return out


def _resolve(code: str):
    """Return the current active Questionnaire for a stable code, or None."""
    try:
        return Questionnaire.objects.filter(code=code, status="AC").first()
    except (AttributeError, ValueError) as exc:
        log.warning(f"questionnaire resolve failed for code={code}: {exc}")
        return None


def _option_value(option) -> str:
    """Stable round-trip value for a response option (code, else dbid)."""
    return option.code or str(option.dbid)


def _kind(question_type) -> str:
    """Normalize the raw SDK question type to a render kind for the modal."""
    mapping = {
        ResponseOption.TYPE_TEXT: "text",
        ResponseOption.TYPE_INTEGER: "integer",
        ResponseOption.TYPE_RADIO: "radio",
        ResponseOption.TYPE_CHECKBOX: "checkbox",
    }
    return mapping.get(question_type, "text")


def question_schema(code: str) -> list[dict]:
    """Return the questionnaire's questions/options for live rendering, or []."""
    questionnaire = _resolve(code)
    if not questionnaire:
        return []
    try:
        cmd = QuestionnaireCommand(questionnaire_id=str(questionnaire.id))
        schema = []
        for question in cmd.questions:
            schema.append(
                {
                    "name": question.name,
                    "label": getattr(question, "label", "") or question.name,
                    "kind": _kind(question.type),
                    "options": [
                        {"value": _option_value(o), "label": o.name}
                        for o in (question.options or [])
                    ],
                }
            )
        return schema
    except (AttributeError, ValueError, TypeError) as exc:
        log.warning(f"question schema read failed for code={code}: {exc}")
        return []


def _find_option(question, value: str):
    for option in question.options or []:
        if _option_value(option) == value:
            return option
    return None


def build_command(code: str, note_id: str, answers: dict):
    """Build a populated questionnaire command (caller originates) or None.

    ``answers`` maps question name -> value: a string for text/integer/radio, or
    a list of option values for checkbox.
    """
    questionnaire = _resolve(code)
    if not questionnaire:
        return None
    # Accessing cmd.questions raises ValueError on an unsupported question type
    # (same as question_schema); degrade to None so one misconfigured
    # questionnaire can't 500 the whole submit endpoint.
    try:
        cmd = QuestionnaireCommand(questionnaire_id=str(questionnaire.id))
        cmd.note_uuid = note_id
        cmd.command_uuid = str(uuid4())
        for question in cmd.questions:
            answer = (answers or {}).get(question.name)
            if answer is None or answer == "" or answer == []:
                continue
            qtype = question.type
            if qtype == ResponseOption.TYPE_TEXT:
                question.add_response(text=str(answer))
            elif qtype == ResponseOption.TYPE_INTEGER:
                try:
                    question.add_response(integer=int(answer))
                except (TypeError, ValueError):
                    continue
            elif qtype == ResponseOption.TYPE_RADIO:
                option = _find_option(question, answer)
                if option is not None:
                    question.add_response(option=option)
            elif qtype == ResponseOption.TYPE_CHECKBOX:
                selected = answer if isinstance(answer, list) else [answer]
                for value in selected:
                    option = _find_option(question, value)
                    if option is not None:
                        question.add_response(option=option, selected=True)
    except (AttributeError, ValueError, TypeError) as exc:
        log.warning(f"build_command failed for questionnaire {code}: {exc}")
        return None
    return cmd
