"""Effect builders for landing group therapy documentation into existing notes.

The plugin never creates a standalone note or an appointment. Documentation is
originated into an attendee's existing appointment note (``target_note_id``),
which the schedule-derived roster already provides.
"""

import json
from uuid import uuid4

from canvas_sdk.commands.commands.assess import AssessCommand
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.commands.commands.perform import PerformCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note

from group_therapy.helpers import build_note_html, build_note_print
from group_therapy.services.questionnaires import build_command


def billing_applies(billing_mode: str, participant_index: int) -> bool:
    """Whether this attendee's note carries the CPT line item.

    Per-participant billing charges every attendee; group billing charges only
    the first attendee (the group's anchor note).
    """
    if billing_mode == "per_participant":
        return True
    return participant_index == 0


def build_documentation_effects(
    *,
    target_note_id: str,
    meta_pairs: list,
    summary_sections: list,
    questionnaire_specs: list | None = None,
    condition_id: str | None = None,
    billing_mode: str = "group",
    cpt_code: str = "",
    sign: bool = False,
    participant_index: int = 0,
    check_in: bool = False,
) -> list[Effect]:
    """Originate one attendee's documentation into their existing note, driven by
    the resolved template:

    - the Group Therapy summary command (header ``meta_pairs`` + free-text /
      read-only ``summary_sections``);
    - the diagnosis (Assess) when ``condition_id`` is set;
    - one populated command per ``questionnaire_specs`` entry
      (``{"code", "answers"}``) - resolved by code, originated for provider
      review (not committed, so the provider verifies before signing);
    - billing (Perform) when it applies for this attendee.

    When ``check_in`` is True (a still-booked appointment) a check-in effect is
    emitted first. Commits perform before assess so BillingAssessmentLinker can
    link the line item. Locks + signs only when ``sign`` is True."""
    effects: list[Effect] = []
    if check_in:
        effects.append(Note(instance_id=target_note_id).check_in())

    content = build_note_html(meta_pairs, summary_sections)
    print_content = build_note_print(meta_pairs, summary_sections)

    custom_cmd = CustomCommand(
        schema_key="groupTherapyNote", content=content, print_content=print_content
    )
    custom_cmd.note_uuid = target_note_id
    custom_cmd.command_uuid = str(uuid4())
    effects.append(custom_cmd.originate())

    assess_cmd = None
    if condition_id:
        assess_cmd = AssessCommand(
            note_uuid=target_note_id, condition_id=condition_id, narrative=""
        )
        assess_cmd.command_uuid = str(uuid4())
        effects.append(assess_cmd.originate())

    # Questionnaire / structured-assessment / exam commands, populated from the
    # group view and resolved by stable code. Originated for the provider to
    # review and sign - not committed here.
    for spec in questionnaire_specs or []:
        cmd = build_command(
            spec.get("code", ""), target_note_id, spec.get("answers") or {}
        )
        if cmd is not None:
            effects.append(cmd.originate())

    perform_cmd = None
    if billing_applies(billing_mode, participant_index):
        perform_cmd = PerformCommand(note_uuid=target_note_id, cpt_code=cpt_code)
        perform_cmd.command_uuid = str(uuid4())
        effects.append(perform_cmd.originate())

    # Commit perform first so the billing line item exists when the assess
    # commit fires (BillingAssessmentLinker links the assessment to it).
    if perform_cmd is not None:
        effects.append(perform_cmd.commit())
    if assess_cmd is not None:
        effects.append(assess_cmd.commit())

    if sign:
        effects.append(
            Effect(type="LOCK_NOTE", payload=json.dumps({"data": {"note": target_note_id}}))
        )
        effects.append(
            Effect(type="SIGN_NOTE", payload=json.dumps({"data": {"note": target_note_id}}))
        )
    return effects


def build_no_show_effects(note_id: str) -> list[Effect]:
    """Mark an absent attendee's existing appointment note as a no-show."""
    return [Note(instance_id=note_id).no_show()]


def build_checkin_effects(note_id: str) -> list[Effect]:
    """Check in an attendee's scheduled appointment note (Booked -> Checked in)."""
    return [Note(instance_id=note_id).check_in()]
