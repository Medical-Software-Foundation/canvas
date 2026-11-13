"""What a note already holds, for the in-command panel.

- ``note_diagnoses``: the diagnoses charted on the note, which rules check and
  the panel offers as its "Filter by condition" choices.
- ``added_quickpicks``: quickpicks already added to the note, which the panel
  grays out so the same order isn't placed twice under different diagnoses.

Where each command keeps its diagnosis:

- Diagnose: the ICD-10 code (``data.diagnose.value``).
- Assess: the condition's id (``data.condition.value``), whose ICD-10 coding is
  read from the condition; or, for an Assess that diagnoses a new condition,
  that condition's ICD-10 code in the same place.
- Change Diagnosis: the new code (``data.newConditionCode``); the diagnosis it
  replaces isn't counted.
- Assess Coding Gap: a list of diagnoses (``data.diagnose``), each with its
  ICD-10 coding in ``extra.coding``. A refuted gap isn't counted.

Entered-in-error commands are left out.
"""

from typing import Any

from canvas_sdk.v1.data.command import Command, CommandMetadata
from canvas_sdk.v1.data.condition import Condition

from charting_tools.icd10 import condition_id_of, normalize_icd10
from charting_tools.insertion import QUICKPICK_MARKER_PREFIX

ENTERED_IN_ERROR = "entered_in_error"

# Commands that chart a diagnosis on the note.
DIAGNOSIS_COMMANDS = ("diagnose", "assess", "updateDiagnosis", "assessCodingGap")

# An Assess Coding Gap with this status rejects the gap's diagnoses.
REFUTED = "refute"


def _live_commands(note: Any, schema_keys: tuple[str, ...]) -> Any:
    return (
        Command.objects.filter(
            note_id=note.dbid, schema_key__in=schema_keys, entered_in_error__isnull=True
        )
        .exclude(state=ENTERED_IN_ERROR)
        .order_by("dbid")
    )


def note_diagnoses(note: Any, pending: tuple[str, dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """The note's charted diagnoses, in charting order, one per ICD-10 code.

    ``pending`` is a diagnosis command's ``(schema_key, data)`` from the event
    being handled, counted as well, in case that command isn't readable yet.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    condition_refs: list[tuple[int, str]] = []

    def add(code: str, label: str) -> None:
        normal = normalize_icd10(code)
        if normal and normal not in seen:
            seen.add(normal)
            found.append({"code": normal, "label": label or code})

    commands = [(command.schema_key, command.data or {}) for command in _live_commands(note, DIAGNOSIS_COMMANDS)]
    if pending is not None and pending[0] in DIAGNOSIS_COMMANDS:
        commands.append(pending)
    for schema_key, data in commands:
        if schema_key == "diagnose":
            diagnose = data.get("diagnose") or {}
            add(str(diagnose.get("value") or ""), str(diagnose.get("text") or ""))
        elif schema_key == "updateDiagnosis":
            new = data.get("newConditionCode")
            if isinstance(new, dict):
                add(str(new.get("value") or ""), str(new.get("text") or ""))
            elif new:
                add(str(new), "")
        elif schema_key == "assessCodingGap":
            if data.get("status") == REFUTED:
                continue
            for picked in data.get("diagnose") or []:
                if isinstance(picked, dict):
                    add(_icd10_of(picked), str(picked.get("text") or ""))
        else:
            condition = data.get("condition") or {}
            ref = condition_id_of(condition.get("value"))
            if ref is not None:
                condition_refs.append((ref, str(condition.get("text") or "")))
            elif condition.get("value"):
                # An Assess that diagnoses a new condition holds its ICD-10 code.
                add(str(condition["value"]), str(condition.get("text") or ""))

    if condition_refs:
        conditions = {
            c.dbid: c
            for c in Condition.objects.filter(
                dbid__in=[ref for ref, _ in condition_refs], entered_in_error__isnull=True
            ).prefetch_related("codings")
        }
        for ref, label in condition_refs:
            condition = conditions.get(ref)
            if condition is None:
                continue
            for coding in condition.codings.all():
                if "icd" in str(coding.system or "").lower() and "10" in str(coding.system or ""):
                    add(str(coding.code or ""), label or str(coding.display or ""))
                    break
    return found


def command_icd10(command_uuid: str) -> str:
    """The dot-stripped ICD-10 code a Diagnose or Assess command is charting, or "".

    A Diagnose stores its code; an Assess stores its condition, whose ICD-10
    coding has the code.
    """
    row = (
        Command.objects.filter(id=command_uuid, entered_in_error__isnull=True)
        .values_list("schema_key", "data")
        .first()
    )
    if row is None:
        return ""
    schema_key, data = row[0], row[1] or {}
    if schema_key == "diagnose":
        return normalize_icd10(str((data.get("diagnose") or {}).get("value") or ""))
    value = (data.get("condition") or {}).get("value") if schema_key == "assess" else None
    condition_id = condition_id_of(value)
    if condition_id is None:
        # An Assess that diagnoses a new condition holds its ICD-10 code.
        return normalize_icd10(str(value or ""))
    condition = (
        Condition.objects.filter(dbid=condition_id, entered_in_error__isnull=True)
        .prefetch_related("codings")
        .first()
    )
    for coding in condition.codings.all() if condition is not None else []:
        system = str(coding.system or "").lower()
        if "icd" in system and "10" in system and coding.code:
            return normalize_icd10(str(coding.code))
    return ""


def _icd10_of(picked: dict[str, Any]) -> str:
    """A picked diagnosis's ICD-10 code: its ICD-10 coding, else its value."""
    for coding in (picked.get("extra") or {}).get("coding") or []:
        system = str(coding.get("system") or "").lower()
        if "icd" in system and "10" in system and coding.get("code"):
            return str(coding["code"])
    return str(picked.get("value") or "")


def added_quickpicks(note: Any) -> set[str]:
    """Ids of the quickpicks already on the note, from the markers their commands carry."""
    keys = CommandMetadata.objects.filter(
        command__note_id=note.dbid,
        command__entered_in_error__isnull=True,
        key__startswith=QUICKPICK_MARKER_PREFIX,
    ).exclude(command__state=ENTERED_IN_ERROR).values_list("key", flat=True)
    return {str(key)[len(QUICKPICK_MARKER_PREFIX):] for key in keys}
