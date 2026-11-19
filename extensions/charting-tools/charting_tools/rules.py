"""Rules: "when the note shows X, add or suggest Y".

A rule is a ``NoteTemplate`` row of kind "rule" whose ``rule`` field holds:

    {
      "match": "all" | "any",
      "conditions": [ ... ],
      "action": {"mode": "suggest" | "insert"},
    }

and its own ``commands``, built like a note template's. Rules saved before rules
held commands carry ``action.target_id`` instead, naming a template to add.

Conditions are evaluated against the note as it is being charted, including
staged commands, so a rule can respond before anything is committed. Answers
are read from each questionnaire command's own data: the Interview a
questionnaire produces does not exist until the command is committed.

Condition types:

- ``diagnosis``: the note has a charted diagnosis (Diagnose, Assess, the new
  diagnosis on Change Diagnosis, or an accepted Assess Coding Gap) covered by
  the picks, ``{"type", "sources", "match_codes"}``. ``match_codes`` is expanded
  through UMLS when the rule is saved, as for quickpicks.
- ``active_condition``: the patient has an active condition (on their problem
  list, not surgical) covered by the picks, ``{"type", "sources", "match_codes"}``,
  expanded the same way.
- ``note_type``: the note is one of the chosen note types,
  ``{"type", "note_types": [{unique_identifier, name}]}``. A note booked for a
  visit counts as the appointment's note type (the type it becomes at
  check-in), since until then it carries Canvas's generic Appointment type.
- ``score``: a questionnaire's score compares to a number,
  ``{"type", "questionnaire": {code_system, code, name, schema_key}, "op", "value"}``.
  The score sums the values of the chosen options (and numeric answers).
- ``answer``: a question's answer is one of the given options,
  ``{"type", "questionnaire", "question": {key, label}, "options": [{key, label}]}``.
- ``metadata``: a patient, appointment, or note metadata value, as it stands,
  ``{"type", "source": "patient" | "appointment" | "note", "key", "op", "values"}``
  where ``op`` is "equals", "any_of", "present", or "absent". Appointment means
  the note's most recent appointment. Values compare trimmed and case-insensitively.

Questionnaires, questions, and options are referred to by code, which stays the
same across questionnaire versions.
"""

from typing import Any

from canvas_sdk.v1.data.appointment import Appointment, AppointmentMetadata
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.note import NoteMetadata
from canvas_sdk.v1.data.patient import PatientMetadata
from canvas_sdk.v1.data.questionnaire import Questionnaire

from charting_tools.diagnoses import clean_sources
from charting_tools.icd10 import normalize_icd10
from charting_tools.note_conditions import DIAGNOSIS_COMMANDS, note_diagnoses
from charting_tools.note_types import note_type_identifier
from charting_tools.questionnaires import USE_CASE_BY_COMMAND

DIAGNOSIS = "diagnosis"
SCORE = "score"
ANSWER = "answer"
METADATA = "metadata"
ACTIVE_CONDITION = "active_condition"
NOTE_TYPE = "note_type"
CONDITION_TYPES = (DIAGNOSIS, ACTIVE_CONDITION, NOTE_TYPE, SCORE, ANSWER, METADATA)
# Condition types picked from ICD-10 codes and expanded when the rule is saved.
CODED_CONDITION_TYPES = (DIAGNOSIS, ACTIVE_CONDITION)

METADATA_SOURCES = ("patient", "appointment", "note")
METADATA_OPS = ("equals", "any_of", "present", "absent")

# Not a command type: the moment a note is created or its appointment booked.
CREATED = "created"

# Not a command type: an appointment's visit type (its note type) was changed.
VISIT_TYPE = "visit_type"

# Not a command type: a condition on the patient's problem list was added,
# changed, or resolved.
PATIENT_CONDITIONS = "patient_conditions"


def metadata_changed(source: str) -> str:
    """Not a command type: a patient, appointment, or note metadata value was saved."""
    return f"metadata:{source}"

SUGGEST = "suggest"
INSERT = "insert"

OPERATORS = (">=", ">", "=", "<=", "<")


def compare(op: str, left: float, right: float) -> bool:
    """Apply a saved comparison operator."""
    if op == ">=":
        return left >= right
    if op == ">":
        return left > right
    if op == "=":
        return left == right
    if op == "<=":
        return left <= right
    return left < right

MAX_CONDITIONS = 10

# The command types each condition type reads, so the engine can skip a rule
# when the command that changed can't affect it.
QUESTIONNAIRE_COMMANDS = tuple(USE_CASE_BY_COMMAND)


# ── Saving ──────────────────────────────────────────────────────────


def _questionnaire_ref(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict) or not str(raw.get("code") or ""):
        return None
    schema_key = str(raw.get("schema_key") or "questionnaire")
    if schema_key not in USE_CASE_BY_COMMAND:
        return None
    return {
        "code_system": str(raw.get("code_system") or ""),
        "code": str(raw.get("code") or ""),
        "name": str(raw.get("name") or ""),
        "schema_key": schema_key,
    }


def clean_rule(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(rule, None)`` for a well-formed rule, or ``(None, error)``.

    Diagnosis conditions come back without ``match_codes``; the caller expands
    their sources (it holds the UMLS key).
    """
    if not isinstance(raw, dict):
        return None, "Set up when the rule runs"
    match = raw.get("match") if raw.get("match") in ("all", "any") else "all"
    conditions_raw = raw.get("conditions")
    if not isinstance(conditions_raw, list) or not conditions_raw:
        return None, "Add at least one condition"
    if len(conditions_raw) > MAX_CONDITIONS:
        return None, f"A rule can have at most {MAX_CONDITIONS} conditions"

    conditions: list[dict[str, Any]] = []
    for index, item in enumerate(conditions_raw, start=1):
        kind = item.get("type") if isinstance(item, dict) else None
        if kind in CODED_CONDITION_TYPES:
            sources = clean_sources(item.get("sources"))
            if not sources:
                return None, f"Condition {index}: choose at least one diagnosis"
            conditions.append({"type": kind, "sources": sources})
        elif kind == NOTE_TYPE:
            note_types = [
                {"unique_identifier": str(nt["unique_identifier"]), "name": str(nt.get("name") or "")}
                for nt in item.get("note_types") or []
                if isinstance(nt, dict) and nt.get("unique_identifier")
            ]
            if not note_types:
                return None, f"Condition {index}: choose at least one note type"
            conditions.append({"type": NOTE_TYPE, "note_types": note_types})
        elif kind == SCORE:
            questionnaire = _questionnaire_ref(item.get("questionnaire"))
            if questionnaire is None:
                return None, f"Condition {index}: choose a questionnaire"
            if item.get("op") not in OPERATORS:
                return None, f"Condition {index}: choose how to compare the score"
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                return None, f"Condition {index}: enter the score to compare against"
            conditions.append({"type": SCORE, "questionnaire": questionnaire, "op": item["op"], "value": value})
        elif kind == ANSWER:
            questionnaire = _questionnaire_ref(item.get("questionnaire"))
            question = item.get("question") if isinstance(item.get("question"), dict) else {}
            options = [
                {"key": str(o.get("key") or ""), "label": str(o.get("label") or "")}
                for o in item.get("options") or []
                if isinstance(o, dict) and o.get("key")
            ]
            if questionnaire is None:
                return None, f"Condition {index}: choose a questionnaire"
            if not question.get("key"):
                return None, f"Condition {index}: choose a question"
            if not options:
                return None, f"Condition {index}: choose at least one answer"
            conditions.append(
                {
                    "type": ANSWER,
                    "questionnaire": questionnaire,
                    "question": {"key": str(question["key"]), "label": str(question.get("label") or "")},
                    "options": options,
                }
            )
        elif kind == METADATA:
            source = item.get("source")
            key = str(item.get("key") or "").strip()
            op = item.get("op")
            values = [str(v).strip() for v in item.get("values") or [] if str(v).strip()]
            if source not in METADATA_SOURCES:
                return None, f"Condition {index}: choose patient, appointment, or note"
            if not key:
                return None, f"Condition {index}: enter the field's key"
            if op not in METADATA_OPS:
                return None, f"Condition {index}: choose how to compare the value"
            if op in ("equals", "any_of") and not values:
                return None, f"Condition {index}: enter the value to match"
            conditions.append(
                {"type": METADATA, "source": source, "key": key, "op": op, "values": values[:1] if op == "equals" else values}
            )
        else:
            return None, f"Condition {index}: choose what to check"

    action_raw: dict[str, Any] = raw["action"] if isinstance(raw.get("action"), dict) else {}
    mode = INSERT if action_raw.get("mode") == INSERT else SUGGEST
    return {"match": match, "conditions": conditions, "action": {"mode": mode}}, None


def watched_commands(rule: dict[str, Any]) -> set[str]:
    """Command types whose changes can change this rule's outcome."""
    watched: set[str] = set()
    for condition in rule.get("conditions") or []:
        if condition.get("type") == DIAGNOSIS:
            watched.update(DIAGNOSIS_COMMANDS)
        elif condition.get("type") == NOTE_TYPE:
            watched.add(CREATED)
            watched.add(VISIT_TYPE)
        elif condition.get("type") == ACTIVE_CONDITION:
            watched.add(CREATED)
            watched.add(PATIENT_CONDITIONS)
        elif condition.get("type") == METADATA:
            watched.add(CREATED)
            watched.add(metadata_changed(condition.get("source") or ""))
        else:
            watched.add(condition.get("questionnaire", {}).get("schema_key") or "questionnaire")
    return watched


# ── Evaluating ──────────────────────────────────────────────────────


class NoteState:
    """What a note holds right now, read once per event and shared by every rule."""

    def __init__(self, note: Any, pending: tuple[str, dict[str, Any]] | None = None) -> None:
        self.note = note
        # The diagnosis command the event is about, as the event reports it.
        self.pending = pending
        self._diagnoses: set[str] | None = None
        self._active_conditions: set[str] | None = None
        self._appointment: Any = None
        self._appointment_read = False
        self._questionnaire_commands: list[dict[str, Any]] | None = None
        self._versions: dict[tuple[str, str], set[int]] = {}
        self._metadata: dict[str, dict[str, str]] = {}

    def metadata(self, source: str) -> dict[str, str]:
        """Current metadata for the note's patient, its latest appointment, or the note."""
        if source not in self._metadata:
            rows: Any = []
            if source == "patient" and getattr(self.note, "patient_id", None):
                rows = PatientMetadata.objects.filter(patient_id=self.note.patient_id)
            elif source == "note":
                rows = NoteMetadata.objects.filter(note_id=self.note.dbid)
            elif source == "appointment":
                appointment = self.appointment()
                if appointment is not None:
                    rows = AppointmentMetadata.objects.filter(appointment_id=appointment.dbid)
            self._metadata[source] = {str(r.key): str(r.value or "") for r in rows}
        return self._metadata[source]

    def appointment(self) -> Any:
        """The note's latest appointment, if it is a visit note."""
        if not self._appointment_read:
            self._appointment_read = True
            self._appointment = (
                Appointment.objects.select_related("note_type")
                .filter(note_id=self.note.dbid, entered_in_error__isnull=True)
                .order_by("-dbid")
                .first()
            )
        return self._appointment

    def note_type(self) -> str | None:
        """The note's type, or for a visit note the appointment's note type."""
        appointment = self.appointment()
        if appointment is not None and appointment.note_type is not None:
            return str(appointment.note_type.unique_identifier)
        return note_type_identifier(self.note)

    def active_conditions(self) -> set[str]:
        """Dot-stripped ICD-10 codes of the patient's active, non-surgical conditions."""
        if self._active_conditions is None:
            codes: set[str] = set()
            patient_id = getattr(self.note, "patient_id", None)
            if patient_id:
                for condition in (
                    Condition.objects.active()
                    .filter(patient_id=patient_id, deleted=False, surgical=False)
                    .prefetch_related("codings")
                ):
                    for coding in condition.codings.all():
                        system = str(coding.system or "").lower()
                        if "icd" in system and "10" in system and coding.code:
                            codes.add(normalize_icd10(str(coding.code)))
            self._active_conditions = codes
        return self._active_conditions

    def diagnoses(self) -> set[str]:
        """Dot-stripped ICD-10 codes charted on the note."""
        if self._diagnoses is None:
            self._diagnoses = {d["code"] for d in note_diagnoses(self.note, self.pending)}
        return self._diagnoses

    def questionnaire_commands(self) -> list[dict[str, Any]]:
        """The data of every live questionnaire-type command on the note."""
        if self._questionnaire_commands is None:
            self._questionnaire_commands = [
                command.data or {}
                for command in Command.objects.filter(
                    note_id=self.note.dbid,
                    schema_key__in=QUESTIONNAIRE_COMMANDS,
                    entered_in_error__isnull=True,
                ).exclude(state="entered_in_error")
            ]
        return self._questionnaire_commands

    def versions(self, ref: dict[str, str]) -> set[int]:
        """Database ids of every version of a questionnaire, by its code."""
        key = (ref.get("code_system", ""), ref.get("code", ""))
        if key not in self._versions:
            self._versions[key] = set(
                Questionnaire.objects.filter(code_system=key[0], code=key[1]).values_list("dbid", flat=True)
            )
        return self._versions[key]

    def responses(self, ref: dict[str, str]) -> list[dict[str, Any]]:
        """Each matching questionnaire on the note, as ``{question key: [(option code, value) | answer]}``."""
        versions = self.versions(ref)
        found = []
        for data in self.questionnaire_commands():
            chosen = data.get("questionnaire") or {}
            if _as_int(chosen.get("value")) not in versions:
                continue
            found.append(read_answers(data))
        return found


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_answers(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A staged questionnaire command's answers, keyed by question code.

    Each entry is ``{"options": [(option code, numeric value)], "number": float | None}``.
    """
    extra = (data.get("questionnaire") or {}).get("extra") or {}
    out: dict[str, dict[str, Any]] = {}
    for question in extra.get("questions") or []:
        name = question.get("name") or f"question-{question.get('pk')}"
        if name not in data or data[name] in (None, "", []):
            continue
        coding = question.get("coding") or {}
        code = str(coding.get("code") or "")
        key = f"{coding.get('system') or ''}|{code}" if code else f"label|{question.get('label') or ''}"
        options = {str(o.get("pk")): o for o in question.get("options") or []}
        value = data[name]
        picked: list[tuple[str, float | None]] = []
        number = None
        if question.get("type") == "MULT":
            for selection in value if isinstance(value, list) else []:
                if isinstance(selection, dict) and selection.get("selected"):
                    option = options.get(str(selection.get("value")))
                    if option is not None:
                        picked.append((str(option.get("code") or option.get("label") or ""), _number(option.get("value"))))
        elif question.get("type") == "SING":
            option = options.get(str(value))
            if option is not None:
                picked.append((str(option.get("code") or option.get("label") or ""), _number(option.get("value"))))
        else:
            number = _number(value)
        out[key] = {"options": picked, "number": number}
    return out


def score(answers: dict[str, dict[str, Any]]) -> float:
    """Sum of chosen options' values and numeric answers."""
    total = 0.0
    for answer in answers.values():
        for _, value in answer["options"]:
            total += value or 0
        if answer["number"] is not None:
            total += answer["number"]
    return total


def condition_met(condition: dict[str, Any], state: NoteState) -> bool:
    """Whether one condition holds for the note right now."""
    kind = condition.get("type")
    if kind == DIAGNOSIS:
        codes = set(condition.get("match_codes") or [])
        return bool(codes & state.diagnoses())
    if kind == NOTE_TYPE:
        wanted = {nt["unique_identifier"] for nt in condition.get("note_types") or []}
        return state.note_type() in wanted
    if kind == ACTIVE_CONDITION:
        codes = set(condition.get("match_codes") or [])
        return bool(codes & state.active_conditions())
    if kind == SCORE:
        return any(
            compare(condition["op"], score(answers), condition["value"])
            for answers in state.responses(condition["questionnaire"])
        )
    if kind == METADATA:
        values = state.metadata(condition["source"])
        present = condition["key"] in values and values[condition["key"]].strip() != ""
        if condition["op"] == "present":
            return present
        if condition["op"] == "absent":
            return not present
        actual = values.get(condition["key"], "").strip().casefold()
        return present and actual in {str(v).strip().casefold() for v in condition.get("values") or []}
    if kind == ANSWER:
        wanted = {o["key"] for o in condition.get("options") or []}
        key = condition["question"]["key"]
        return any(
            wanted & {code for code, _ in answers.get(key, {}).get("options", [])}
            for answers in state.responses(condition["questionnaire"])
        )
    return False


def rule_met(rule: dict[str, Any], state: NoteState) -> bool:
    """Whether a rule's conditions hold, per its all/any setting."""
    results = (condition_met(c, state) for c in rule.get("conditions") or [])
    return any(results) if rule.get("match") == "any" else all(results)


def normalize_codes(codes: list[str]) -> list[str]:
    """Dot-stripped codes, de-duplicated in order."""
    out: list[str] = []
    for code in codes:
        normal = normalize_icd10(code)
        if normal and normal not in out:
            out.append(normal)
    return out
