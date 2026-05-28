"""Chat-tool registry and dispatchers.

Each tool lives in its own module under `assistant.chat_tools`. A tool module
exposes three things at module level:
    - an args pydantic model (e.g. `FindPatientsArgs(BaseModel)`)
    - a free-function handler (e.g. `def find_patients(instance, args): ...`)
    - a `TOOL_SPEC: dict` literal describing the tool

The handler signature is `(instance, args) -> dict` for read-only tools and
`(instance, args, staff_id) -> tuple[dict, list[Effect]]` for mutations
(`mutates: True` in the spec).

This module imports each tool module and assembles `CHAT_TOOL_REGISTRY` by
reading each module's `TOOL_SPEC` attribute. The schema (`input_schema`) is
derived from `args_model.model_json_schema()` here, not in each module — keeps
the spec dicts tight and centralizes schema-generation policy.

Why the explicit-imports pattern + sibling `chat_tools_lib` module:
Plugin code runs under RestrictedPython, which re-evaluates module `__init__`
files when a submodule imports back into its own package mid-load. Decorator-
based registration (closure over a shared registry list) doesn't survive that
re-evaluation: each Sandbox produces a distinct list object, and the consumer
reads an empty one. The attribute-based assembly here works because each
tool module's TOOL_SPEC is a deterministic value read at the end. Shared
helpers (`apply_filter_args`, `DEFAULT_RESULT_LIMIT`, `MAX_RESULT_LIMIT`) live
in `assistant.chat_tools_lib` (sibling to this package) so tool modules can
import them without re-triggering this `__init__.py` mid-load.

`assistant.handlers.assistant` consumes the registry in three places:
  * `_execute_tool` calls `dispatch_chat_tool(self, name, args)` for read-only
    tools. Returns `{"error": ...}` for unknown names.
  * The chat loop calls `is_mutating_tool(name)` to decide whether to pause for
    user approval before executing a tool_use block.
  * On approval, `dispatch_mutation(self, name, args, staff_id)` runs the
    mutation and returns `(result_dict, effects_to_apply)`.

Tool ordering matches the import order below. Inserting a tool in the middle
invalidates the Anthropic prompt-cache prefix; that's a one-time cost on the
deploy that adds it, not an ongoing concern.
"""

from typing import Any

from pydantic import ValidationError

# Direct submodule imports — NOT `from assistant.chat_tools import X`, which
# would self-import this package and trigger sandbox recursion. Each
# `from assistant.chat_tools.X import TOOL_SPEC` evaluates X without
# re-triggering __init__.py.
from assistant.chat_tools.count_patients import TOOL_SPEC as _SPEC_COUNT_PATIENTS
from assistant.chat_tools.create_appointment import TOOL_SPEC as _SPEC_CREATE_APPOINTMENT
from assistant.chat_tools.create_condition import TOOL_SPEC as _SPEC_CREATE_CONDITION
from assistant.chat_tools.create_task import TOOL_SPEC as _SPEC_CREATE_TASK
from assistant.chat_tools.find_allergies import TOOL_SPEC as _SPEC_FIND_ALLERGIES
from assistant.chat_tools.find_appointments import TOOL_SPEC as _SPEC_FIND_APPOINTMENTS
from assistant.chat_tools.find_commands import TOOL_SPEC as _SPEC_FIND_COMMANDS
from assistant.chat_tools.find_conditions import TOOL_SPEC as _SPEC_FIND_CONDITIONS
from assistant.chat_tools.find_encounters import TOOL_SPEC as _SPEC_FIND_ENCOUNTERS
from assistant.chat_tools.find_lab_reports import TOOL_SPEC as _SPEC_FIND_LAB_REPORTS
from assistant.chat_tools.find_medications import TOOL_SPEC as _SPEC_FIND_MEDICATIONS
from assistant.chat_tools.find_notes import TOOL_SPEC as _SPEC_FIND_NOTES
from assistant.chat_tools.find_observations import TOOL_SPEC as _SPEC_FIND_OBSERVATIONS
from assistant.chat_tools.find_patients import TOOL_SPEC as _SPEC_FIND_PATIENTS
from assistant.chat_tools.find_staff import TOOL_SPEC as _SPEC_FIND_STAFF
from assistant.chat_tools.find_tasks import TOOL_SPEC as _SPEC_FIND_TASKS
from assistant.chat_tools.get_today import TOOL_SPEC as _SPEC_GET_TODAY
from assistant.chat_tools.prep_visit_panel import TOOL_SPEC as _SPEC_PREP_VISIT_PANEL
from canvas_sdk.effects import Effect

_SPECS: tuple[dict[str, Any], ...] = (
    _SPEC_COUNT_PATIENTS,
    _SPEC_CREATE_APPOINTMENT,
    _SPEC_CREATE_CONDITION,
    _SPEC_CREATE_TASK,
    _SPEC_FIND_ALLERGIES,
    _SPEC_FIND_APPOINTMENTS,
    _SPEC_FIND_COMMANDS,
    _SPEC_FIND_CONDITIONS,
    _SPEC_FIND_ENCOUNTERS,
    _SPEC_FIND_LAB_REPORTS,
    _SPEC_FIND_MEDICATIONS,
    _SPEC_FIND_NOTES,
    _SPEC_FIND_OBSERVATIONS,
    _SPEC_FIND_PATIENTS,
    _SPEC_FIND_STAFF,
    _SPEC_FIND_TASKS,
    _SPEC_GET_TODAY,
    _SPEC_PREP_VISIT_PANEL,
)


def _build_registry() -> list[dict[str, Any]]:
    """Assemble CHAT_TOOL_REGISTRY from each module's TOOL_SPEC.

    Adds the derived Anthropic-compatible `schema` field by calling
    `model_json_schema()` on the args model.
    """
    registry: list[dict[str, Any]] = []
    for spec in _SPECS:
        entry = dict(spec)
        entry["schema"] = {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["args_model"].model_json_schema(),
        }
        registry.append(entry)
    return registry


CHAT_TOOL_REGISTRY: list[dict[str, Any]] = _build_registry()
_MUTATING_NAMES: frozenset[str] = frozenset(
    spec["name"] for spec in CHAT_TOOL_REGISTRY if spec["mutates"]
)


def is_mutating_tool(name: str) -> bool:
    """Return True if `name` is a registered mutation (requires user approval)."""
    return name in _MUTATING_NAMES


def dispatch_chat_tool(instance: Any, name: str, arguments: dict | None) -> dict | None:
    """Look up a read-only tool, validate args, and run the handler.

    Returns the handler's JSON-serializable dict on success, an `{"error": ...}`
    dict on validation/runtime failure, or `None` if no read-only tool matches
    `name` (so the caller can surface "unknown tool"). Mutating tools are
    skipped — their execution goes through `dispatch_mutation`.
    """
    for tool in CHAT_TOOL_REGISTRY:
        if tool["name"] == name and not tool["mutates"]:
            try:
                args = tool["args_model"].model_validate(arguments or {})
            except ValidationError as exc:
                return {"error": f"invalid arguments: {exc}"}
            try:
                return tool["handler"](instance, args)
            except Exception as exc:  # noqa: BLE001 — tool errors must not crash the loop
                return {"error": f"{exc.__class__.__name__}: {exc}"}
    return None


def dispatch_mutation(
    instance: Any, name: str, arguments: dict | None, staff_id: str | None
) -> tuple[dict, list[Effect]]:
    """Validate args and execute a registered mutation.

    Returns `(result_dict, effects)`. On unknown tool name, validation error,
    or handler exception, returns `({"error": ...}, [])` so the chat loop can
    surface the error to Claude without crashing.
    """
    for tool in CHAT_TOOL_REGISTRY:
        if tool["name"] == name and tool["mutates"]:
            try:
                args = tool["args_model"].model_validate(arguments or {})
            except ValidationError as exc:
                return {"error": f"invalid arguments: {exc}"}, []
            try:
                return tool["handler"](instance, args, staff_id)
            except Exception as exc:  # noqa: BLE001 — mutation errors must not crash the loop
                return {"error": f"{exc.__class__.__name__}: {exc}"}, []
    return {"error": f"unknown mutation: {name}"}, []
