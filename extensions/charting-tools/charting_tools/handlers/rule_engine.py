"""Runs rules as the note is charted.

Listens to the update events of the commands rules can read (questionnaire-type
commands, and Diagnose, Assess, Change Diagnosis, and Assess Coding Gap), to a
note being created, its appointment booked, or its visit type changed, to
patient, appointment, and note metadata being saved (for rules that check
metadata), and to the patient's conditions being added, changed, or resolved
(for rules that check active conditions). Evaluates every active rule that watches what happened against the note
as it stands, and acts:

A rule runs its actions in order. **Add** actions either suggest their commands
on a Protocol Card or insert them; **update** and **remove** actions act on
uncommitted commands already on the note (never committed ones) and always run
automatically. Automatic actions run once per note.

- **insert**: adds the rule's commands to the note once. A note metadata marker per rule stops it repeating as the
  clinician keeps typing.
- **suggest**: shows the rule's commands as a Protocol Card recommendation whose
  button adds them, and withdraws the card when the conditions stop holding. The last
  state per rule and patient is cached so an unchanged card isn't re-sent on
  every keystroke.

Commands are never removed when a condition stops holding: the clinician may
have edited them.
"""

from typing import Any
from uuid import uuid4

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import Note as NoteEffect
from canvas_sdk.effects.protocol_card import ProtocolCard, Recommendation
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment, AppointmentMetadata, AppointmentProgressStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteMetadata
from logger import log

from charting_tools.command_catalog import CATALOG
from charting_tools.command_forms import apply_form
from charting_tools.insertion import build_commands, template_effects, visit_day
from charting_tools.questionnaires import answers_for
from charting_tools.kinds import RULE, kind_of
from charting_tools.models.note_template import NoteTemplate
from charting_tools.note_conditions import DIAGNOSIS_COMMANDS
from charting_tools.note_states import OPEN_NOTE_STATES
from charting_tools.rules import (
    CREATED,
    INSERT,
    PATIENT_CONDITIONS,
    VISIT_TYPE,
    NoteState,
    metadata_changed,
    rule_met,
    watched_commands,
)

RULE_MARKER_PREFIX = "charting_tools:rule:"
CARD_STATE_TTL_SECONDS = 43200
RUN_CLAIM_SECONDS = 600

# Event -> the command type it reports on.
WATCHED_EVENTS = {
    EventType.QUESTIONNAIRE_COMMAND__POST_UPDATE: "questionnaire",
    EventType.ROS_COMMAND__POST_UPDATE: "ros",
    EventType.PHYSICAL_EXAM_COMMAND__POST_UPDATE: "exam",
    EventType.STRUCTURED_ASSESSMENT_COMMAND__POST_UPDATE: "structuredAssessment",
    # Diagnosis commands also on being added: one started from the chart (the
    # Assess button on a condition) arrives with its diagnosis already filled in
    # and may never be edited.
    EventType.DIAGNOSE_COMMAND__POST_ORIGINATE: "diagnose",
    EventType.DIAGNOSE_COMMAND__POST_INSERTED_INTO_NOTE: "diagnose",
    EventType.DIAGNOSE_COMMAND__POST_UPDATE: "diagnose",
    EventType.ASSESS_COMMAND__POST_ORIGINATE: "assess",
    EventType.ASSESS_COMMAND__POST_INSERTED_INTO_NOTE: "assess",
    EventType.ASSESS_COMMAND__POST_UPDATE: "assess",
    EventType.ASSESS_COMMAND__CONDITION_SELECTED: "assess",
    EventType.UPDATE_DIAGNOSIS_COMMAND__POST_ORIGINATE: "updateDiagnosis",
    EventType.UPDATE_DIAGNOSIS_COMMAND__POST_INSERTED_INTO_NOTE: "updateDiagnosis",
    EventType.UPDATE_DIAGNOSIS_COMMAND__POST_UPDATE: "updateDiagnosis",
    EventType.ASSESS_CODING_GAP_COMMAND__POST_ORIGINATE: "assessCodingGap",
    EventType.ASSESS_CODING_GAP_COMMAND__POST_INSERTED_INTO_NOTE: "assessCodingGap",
    EventType.ASSESS_CODING_GAP_COMMAND__POST_UPDATE: "assessCodingGap",
    # A booked visit's note exists by then, with the scheduling form's
    # appointment metadata saved in the same transaction.
    EventType.NOTE_CREATED: CREATED,
    EventType.APPOINTMENT_CREATED: CREATED,
    # The visit type (the appointment's note type) changing.
    EventType.APPOINTMENT_UPDATED: VISIT_TYPE,
    # Metadata saved later, by a person or another plugin.
    EventType.PATIENT_METADATA_CREATED: metadata_changed("patient"),
    EventType.PATIENT_METADATA_UPDATED: metadata_changed("patient"),
    EventType.APPOINTMENT_METADATA_CREATED: metadata_changed("appointment"),
    EventType.APPOINTMENT_METADATA_UPDATED: metadata_changed("appointment"),
    EventType.NOTE_METADATA_CREATED: metadata_changed("note"),
    EventType.NOTE_METADATA_UPDATED: metadata_changed("note"),
    # The patient's problem list changing.
    EventType.CONDITION_CREATED: PATIENT_CONDITIONS,
    EventType.CONDITION_UPDATED: PATIENT_CONDITIONS,
    EventType.CONDITION_RESOLVED: PATIENT_CONDITIONS,
}

# Events about the patient rather than one note: they re-check the patient's open notes.
PATIENT_EVENTS = (
    EventType.PATIENT_METADATA_CREATED,
    EventType.PATIENT_METADATA_UPDATED,
    EventType.CONDITION_CREATED,
    EventType.CONDITION_UPDATED,
    EventType.CONDITION_RESOLVED,
)

# This plugin's own note metadata (rule and template markers). Saving it never
# re-runs rules, or every rule action would trigger another evaluation.
OWN_METADATA_PREFIX = "charting_tools:"

# A patient metadata or problem list change re-checks the patient's notes still
# being charted, most recent first, up to this many, looking among their most
# recent PATIENT_NOTES_SCANNED notes.
MAX_PATIENT_NOTES = 10
PATIENT_NOTES_SCANNED = 50

# The note body columns, to leave out when a note is reached through another
# model: rules never read the body, and it can be large.
NOTE_BODY_THROUGH_NOTE = ("note___body", "note___body_content", "note___body_order")


def _notes_query() -> Any:
    """Notes with their patient, without the body."""
    return Note.objects.select_related("patient").defer("body")



def card_key(rule_id: str) -> str:
    """The Protocol Card key for a rule's suggestion."""
    return f"charting_tools_rule_{rule_id}"


class RuleEngine(BaseHandler):
    """Evaluate rules when a command they read changes."""

    RESPONDS_TO = [EventType.Name(event) for event in WATCHED_EVENTS]

    def compute(self) -> list[Effect]:
        """Act on every active rule that watches the command that changed."""
        changed = WATCHED_EVENTS.get(self.event.type)
        if changed is None:
            return []
        rules = [
            row
            for row in NoteTemplate.objects.filter(active=True, kind=RULE).order_by("name")
            if changed in watched_commands(row.rule or {})
        ]
        if not rules:
            return []

        notes = self._notes()
        log.info(
            f"{EventType.Name(self.event.type)}: {len(rules)} rule(s) to check on {len(notes)} note(s)"
        )
        effects: list[Effect] = []
        for note in notes:
            effects.extend(self._evaluate(note, rules, changed))
        return effects

    def _evaluate(self, note: Any, rules: list[Any], changed: str) -> list[Effect]:
        """Act on each rule for one note."""
        state = NoteState(note, self._pending(changed))
        fired = set(
            str(key)[len(RULE_MARKER_PREFIX):]
            for key in NoteMetadata.objects.filter(
                note_id=note.dbid, key__startswith=RULE_MARKER_PREFIX
            ).values_list("key", flat=True)
        )

        effects: list[Effect] = []
        for rule in rules:
            spec = rule.rule or {}
            actions = self._actions(rule, spec)
            if not actions:
                log.warning(f"Rule {rule.template_id} has nothing to do")
                continue
            met = rule_met(spec, state)
            suggested = [a for a in actions if a["type"] == "add" and a.get("mode") != INSERT]
            automatic = [a for a in actions if a not in suggested]
            if suggested:
                effects.extend(self._suggest(rule, suggested, note, met))
            if met and automatic and rule.template_id not in fired:
                effects.extend(self._run(rule, automatic, note, state))
        return effects

    def _actions(self, rule: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """The rule's actions, reading rules saved before actions existed as one add."""
        if spec.get("actions"):
            return list(spec["actions"])
        mode = (spec.get("action") or {}).get("mode")
        if rule.commands:
            return [{"type": "add", "mode": mode, "commands": rule.commands}]
        target = self._target(spec)
        return [{"type": "add", "mode": mode, "commands": target.commands}] if target is not None else []

    def _run(self, rule: Any, actions: list[dict[str, Any]], note: Any, state: NoteState) -> list[Effect]:
        """Carry out a rule's automatic actions in order, then mark the note."""
        effects: list[Effect] = []
        for action in actions:
            if action["type"] == "add":
                effects.extend(
                    template_effects(_Commands(rule, action["commands"]), note, self.secrets, replace_line=False)
                )
            elif action["type"] == "update":
                effects.extend(update_effects(action, note, state))
            elif action["type"] == "delete":
                effects.extend(delete_effects(action, note, state))
        if not effects:
            return []
        # Adding a diagnosis command sends several events at once, each of which
        # can get here before the note marker below is saved. The first to claim
        # the rule for this note acts; the rest stand down.
        claim = str(uuid4())
        claimed = get_cache().get_or_set(
            f"charting_tools_rule_run:{rule.template_id}:{note.id}", claim, timeout_seconds=RUN_CLAIM_SECONDS
        )
        if claimed != claim:
            return []
        log.info(f"Rule {rule.template_id} acted on note {note.id}")
        marker = NoteEffect(instance_id=str(note.id)).upsert_metadata(
            key=f"{RULE_MARKER_PREFIX}{rule.template_id}", value="1"
        )
        return [*effects, marker]

    def _pending(self, changed: str) -> tuple[str, dict[str, Any]] | None:
        """The diagnosis command this event reports, with its fields as the event has them."""
        if changed not in DIAGNOSIS_COMMANDS:
            return None
        context = self.event.context if isinstance(self.event.context, dict) else {}
        fields = context.get("fields")
        return (changed, fields) if isinstance(fields, dict) else None

    def _notes(self) -> list[Any]:
        """The notes this event can change a rule's outcome on."""
        event_type = self.event.type
        context = self.event.context if isinstance(self.event.context, dict) else {}
        if event_type in (EventType.NOTE_METADATA_CREATED, EventType.NOTE_METADATA_UPDATED):
            row = NoteMetadata.objects.filter(id=self.event.target.id).values_list("key", "note_id").first()
            if row is None or str(row[0]).startswith(OWN_METADATA_PREFIX):
                return []
            note = _notes_query().filter(dbid=row[1]).first()
            return [note] if note is not None and self._open(note) else []
        if event_type in (EventType.APPOINTMENT_METADATA_CREATED, EventType.APPOINTMENT_METADATA_UPDATED):
            appointment_id = (context.get("appointment") or {}).get("id")
            if not appointment_id:
                appointment_id = (
                    AppointmentMetadata.objects.filter(id=self.event.target.id)
                    .values_list("appointment__id", flat=True)
                    .first()
                )
            appointment = (
                Appointment.objects.select_related("note", "note__patient")
                .defer(*NOTE_BODY_THROUGH_NOTE)
                .filter(id=appointment_id, entered_in_error__isnull=True)
                .first()
                if appointment_id
                else None
            )
            note = appointment.note if appointment is not None else None
            if note is None:
                log.info(f"Appointment metadata {self.event.target.id}: no appointment note found")
                return []
            if not self._open(note):
                log.info(f"Appointment metadata {self.event.target.id}: note {note.id} is not open")
                return []
            return [note]
        if event_type == EventType.APPOINTMENT_UPDATED:
            appointment = (
                Appointment.objects.select_related("note", "note__patient")
                .defer(*NOTE_BODY_THROUGH_NOTE)
                .filter(id=self.event.target.id, entered_in_error__isnull=True)
                .exclude(status__in=(AppointmentProgressStatus.CANCELLED, AppointmentProgressStatus.NOSHOWED))
                .first()
            )
            note = appointment.note if appointment is not None else None
            if note is None or not self._open(note):
                return []
            # A reschedule also updates the appointment it replaced; only the
            # note's latest appointment says what the visit is now.
            latest = (
                Appointment.objects.filter(note_id=note.dbid, entered_in_error__isnull=True)
                .order_by("-dbid")
                .values_list("id", flat=True)
                .first()
            )
            return [note] if str(latest) == str(appointment.id) else []
        if event_type in PATIENT_EVENTS:
            patient_id = (context.get("patient") or {}).get("id")
            if not patient_id:
                return []
            # The patient's recent notes, then their states by note id. Filtering
            # notes on current_state joins the current-state view, which makes the
            # database derive every note's state on the instance first.
            recent = list(
                _notes_query().filter(patient__id=patient_id).order_by("-dbid")[:PATIENT_NOTES_SCANNED]
            )
            open_ids = set(
                CurrentNoteStateEvent.objects.filter(
                    note_id__in=[n.dbid for n in recent], state__in=OPEN_NOTE_STATES
                ).values_list("note_id", flat=True)
            )
            return [n for n in recent if n.dbid in open_ids][:MAX_PATIENT_NOTES]
        note = self._note()
        return [note] if note is not None else []

    def _open(self, note: Any) -> bool:
        return bool(
            CurrentNoteStateEvent.objects.filter(note_id=note.dbid, state__in=OPEN_NOTE_STATES).exists()
        )

    def _note(self) -> Any:
        if self.event.type == EventType.NOTE_CREATED:
            return _notes_query().filter(id=self.event.target.id).first()
        if self.event.type == EventType.APPOINTMENT_CREATED:
            appointment = (
                Appointment.objects.select_related("note", "note__patient")
                .defer(*NOTE_BODY_THROUGH_NOTE)
                .filter(id=self.event.target.id, entered_in_error__isnull=True)
                .first()
            )
            return appointment.note if appointment is not None else None
        context = self.event.context if isinstance(self.event.context, dict) else {}
        note_uuid = (context.get("note") or {}).get("uuid")
        if note_uuid:
            return _notes_query().filter(id=note_uuid).first()
        command = (
            Command.objects.select_related("note", "note__patient")
            .defer(*NOTE_BODY_THROUGH_NOTE)
            .filter(id=self.event.target.id)
            .first()
        )
        return command.note if command is not None else None

    def _target(self, spec: dict[str, Any]) -> Any:
        target_id = (spec.get("action") or {}).get("target_id")
        target = NoteTemplate.objects.filter(template_id=target_id, active=True).first() if target_id else None
        return target if target is not None and kind_of(target) != RULE else None

    def _suggest(self, rule: Any, actions: list[dict[str, Any]], note: Any, met: bool) -> list[Effect]:
        patient_id = str(note.patient.id) if getattr(note, "patient", None) else ""
        if not patient_id:
            return []
        cache = get_cache()
        state_key = f"charting_tools_rule_card:{rule.template_id}:{patient_id}"
        wanted = f"due:{note.id}" if met else "withdrawn"
        if cache.get(state_key) == wanted:
            return []
        cache.set(state_key, wanted, timeout_seconds=CARD_STATE_TTL_SECONDS)

        if not met:
            return [
                ProtocolCard(
                    patient_id=patient_id,
                    key=card_key(rule.template_id),
                    title=rule.name,
                    status=ProtocolCard.Status.NOT_APPLICABLE,
                ).apply()
            ]
        recommendations = []
        for action in actions:
            commands = [item.command for item in build_commands(_Commands(rule, action["commands"]), note)]
            if commands:
                recommendations.append(Recommendation(title=rule.name, button="Add", commands=commands))
        return [
            ProtocolCard(
                patient_id=patient_id,
                key=card_key(rule.template_id),
                title=rule.name,
                narrative="Suggested for this note.",
                status=ProtocolCard.Status.DUE,
                recommendations=recommendations,
            ).apply()
        ]


class _Commands:
    """A rule's add action, shaped like a template so it builds the same way."""

    def __init__(self, rule: Any, commands: list[dict[str, Any]]) -> None:
        self.template_id = rule.template_id
        self.kind = RULE
        self.commands = commands


def _staged_matches(target: dict[str, Any], note: Any, state: NoteState) -> list[Any]:
    """Uncommitted commands on the note that an update or remove action targets.

    Committed commands are never touched. For questionnaire types, only commands
    using one of the chosen questionnaire's versions match.
    """
    rows = list(
        Command.objects.filter(
            note_id=note.dbid,
            schema_key=target["schema_key"],
            state="staged",
            committer__isnull=True,
            entered_in_error__isnull=True,
        ).order_by("dbid")
    )
    questionnaire = target.get("questionnaire")
    if questionnaire:
        versions = state.versions(questionnaire)
        rows = [r for r in rows if _as_int(((r.data or {}).get("questionnaire") or {}).get("value")) in versions]
    return rows


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def update_effects(action: dict[str, Any], note: Any, state: NoteState) -> list[Effect]:
    """Edit each matching uncommitted command with the action's fields and answers.

    Only the fields the action sets are sent, so the rest of the command stays
    as the clinician left it.
    """
    entry = CATALOG[action["target"]["schema_key"]]
    effects: list[Effect] = []
    for row in _staged_matches(action["target"], note, state):
        command = entry.command_class(command_uuid=str(row.id))
        apply_form(command, action.get("fields") or {}, visit_day(note))
        if action.get("answers"):
            command.answers = answers_for(command, action["answers"])
        effects.append(command.edit())
    return effects


def delete_effects(action: dict[str, Any], note: Any, state: NoteState) -> list[Effect]:
    """Remove each matching uncommitted command from the note."""
    entry = CATALOG[action["target"]["schema_key"]]
    return [
        entry.command_class(command_uuid=str(row.id)).delete()
        for row in _staged_matches(action["target"], note, state)
    ]
