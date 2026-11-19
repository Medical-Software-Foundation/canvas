"""Questionnaire selection for questionnaire-type commands.

Templates store a questionnaire by coding system and code, which stay stable
across installations and versions, and resolve it to the active record when
the template is used.
"""

from typing import Any

from canvas_sdk.commands.commands.questionnaire import Answer, Selection
from canvas_sdk.v1.data.questionnaire import Questionnaire

ACTIVE = "AC"

# Questionnaire.carry_forward values. Canvas prefills a newly inserted
# questionnaire-type command from the patient's latest committed answers only
# when the setting is "all"; the plugin sends no answers so that rule applies.
CARRY_FORWARD_OFF = "off"
CARRY_FORWARD_SAME_ENCOUNTER = "same"
CARRY_FORWARD_ALL_ENCOUNTERS = "all"

# Command schema key -> Questionnaire.use_case_in_charting.
USE_CASE_BY_COMMAND = {
    "questionnaire": "QUES",
    "ros": "ROS",
    "exam": "EXAM",
    "structuredAssessment": "SA",
}

QuestionnaireKey = tuple[str, str, str]  # (use_case, code_system, code)


def needs_questionnaire(schema_key: str) -> bool:
    """Return whether this command type is built on a questionnaire."""
    return schema_key in USE_CASE_BY_COMMAND


def options_by_command() -> dict[str, list[dict[str, str]]]:
    """Active, chartable questionnaires grouped by the command type that uses them.

    Questionnaires without a code are left out, since a template can't refer to them stably.
    """
    command_by_use_case = {use_case: key for key, use_case in USE_CASE_BY_COMMAND.items()}
    options: dict[str, list[dict[str, str]]] = {key: [] for key in USE_CASE_BY_COMMAND}
    rows = (
        Questionnaire.objects.filter(
            status=ACTIVE,
            can_originate_in_charting=True,
            use_case_in_charting__in=list(command_by_use_case),
        )
        .exclude(code="")
        .order_by("name")
        .values("name", "code_system", "code", "use_case_in_charting", "carry_forward")
    )
    for row in rows:
        options[command_by_use_case[row["use_case_in_charting"]]].append(
            {
                "name": row["name"],
                "code_system": row["code_system"],
                "code": row["code"],
                # Canvas applies this setting itself when the command is inserted.
                "carry_forward": row["carry_forward"] or CARRY_FORWARD_OFF,
            }
        )
    return options


def key_for(schema_key: str, questionnaire: Any) -> QuestionnaireKey | None:
    """Return the lookup key for a command entry's stored questionnaire, if it has one."""
    if not isinstance(questionnaire, dict):
        return None
    code_system = str(questionnaire.get("code_system") or "")
    code = str(questionnaire.get("code") or "")
    if not code:
        return None
    return (USE_CASE_BY_COMMAND[schema_key], code_system, code)


def resolve(keys: set[QuestionnaireKey]) -> dict[QuestionnaireKey, Any]:
    """Map each key to its active questionnaire, newest first, in one query."""
    if not keys:
        return {}
    found: dict[QuestionnaireKey, Any] = {}
    rows = Questionnaire.objects.filter(
        status=ACTIVE,
        use_case_in_charting__in={use_case for use_case, _, _ in keys},
        code__in={code for _, _, code in keys},
    ).order_by("-dbid")
    for questionnaire in rows:
        key = (
            questionnaire.use_case_in_charting,
            questionnaire.code_system,
            questionnaire.code,
        )
        if key in keys and key not in found:
            found[key] = questionnaire
    return found


# ── Pre-filled answers ──────────────────────────────────────────────
#
# Answers are stored by question code and option code, the identifiers Canvas's
# own questionnaire carry forward matches on, because question and option ids
# change with each questionnaire version. Sending any answer makes Canvas skip
# the questionnaire's own carry forward for that command.

MAX_ANSWER_LENGTH = 4000
ANSWER_TYPES = ("TXT", "INT", "DATE", "SING", "MULT")


def question_key(question: Any) -> str:
    """A version-independent key for a question: its coding, else its label."""
    code = str(getattr(question, "code", "") or "")
    if code:
        return f"{getattr(question, 'code_system', '') or ''}|{code}"
    return f"label|{getattr(question, 'name', '') or getattr(question, 'label', '')}"


def option_key(option: Any) -> str:
    """A version-independent key for a response option: its code, else its name."""
    return str(getattr(option, "code", "") or getattr(option, "name", "") or "")


def question_form(questionnaire: Any) -> list[dict[str, Any]]:
    """The questions of an active questionnaire, shaped for the builder's form."""
    form = []
    for question in questionnaire.questions.select_related("response_option_set").prefetch_related(
        "response_option_set__options"
    ):
        option_set = question.response_option_set
        kind = option_set.type if option_set else None
        if kind not in ANSWER_TYPES:
            continue
        form.append(
            {
                "key": question_key(question),
                "label": question.name,
                "type": kind,
                "options": [
                    {"key": option_key(option), "label": option.name}
                    for option in option_set.options.order_by("ordering")
                ]
                if kind in ("SING", "MULT")
                else [],
            }
        )
    return form


def clean_answers(raw: Any) -> dict[str, Any]:
    """Keep answers shaped as the builder sends them: text, a number, or option keys."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        key = str(key)
        if isinstance(value, bool) or value in (None, "", []):
            continue
        if isinstance(value, list):
            picked = [str(v) for v in value if str(v)]
            if picked:
                out[key] = picked
        elif isinstance(value, int | float):
            out[key] = int(value)
        else:
            out[key] = str(value)[:MAX_ANSWER_LENGTH]
    return out


def answers_for(command: Any, stored: dict[str, Any]) -> list[Any]:
    """Turn stored answers into the SDK's ``Answer`` list for this questionnaire version.

    Questions or options the current version no longer has are skipped, so a
    reworded questionnaire drops those answers instead of failing the insert.
    """
    answers: list[Any] = []
    for question in command.questions:
        coding = getattr(question, "coding", None) or {}
        code = str(coding.get("code") or "")
        key = f"{coding.get('system') or ''}|{code}" if code else f"label|{question.label}"
        if key not in stored:
            continue
        value = stored[key]
        options = {option_key(option): option.dbid for option in question.options}
        if question.type == "SING":
            if str(value) in options:
                answers.append(Answer(question_id=question.id, response=options[str(value)]))
        elif question.type == "MULT":
            picked = [options[str(v)] for v in (value if isinstance(value, list) else [value]) if str(v) in options]
            if picked:
                answers.append(
                    Answer(question_id=question.id, response=[Selection(option_id=dbid) for dbid in picked])
                )
        elif question.type == "INT":
            try:
                answers.append(Answer(question_id=question.id, response=int(str(value).strip())))
            except ValueError:
                continue
        elif question.type in ("TXT", "DATE"):
            answers.append(Answer(question_id=question.id, response=str(value)))
    return answers
