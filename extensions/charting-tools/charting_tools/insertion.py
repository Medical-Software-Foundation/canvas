"""Builds the effects that insert a template's commands into a note.

Shared by the "/" menu entry and the automatic handlers (appointment booking
and direct note creation), so every path inserts exactly the same commands.
"""

from datetime import date, datetime
from typing import Any, Callable
from uuid import uuid4

from canvas_sdk.commands.base import _BaseCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.effects.note import Note as NoteEffect
from canvas_sdk.v1.data.note import Note, NoteMetadata
from logger import log

from charting_tools.carry_forward import (
    apply_carry_forward,
    find_previous_command,
    supports_carry_forward,
)
from charting_tools.command_catalog import CATALOG
from charting_tools.command_forms import LAB_COMMENT_LIMIT, apply_form, lab_variants
from charting_tools.kinds import NON_TEMPLATE_KINDS, QUICKPICK, SECTION_BY_COMMAND, TEMPLATE, kind_of
from charting_tools.labs import preferred_lab_partner_id
from charting_tools.models.note_template import NoteTemplate
from charting_tools.note_types import template_for_note_type
from charting_tools.questionnaires import answers_for, key_for, needs_questionnaire, resolve
from charting_tools.settings import SCRIBE_PROMPT_METADATA_KEY, scribe_enabled


# Canvas's Prescribe command takes at most two indications.
MAX_PRESCRIPTION_INDICATIONS = 2


class Built:
    """A command built from a template entry, with what it came from."""

    def __init__(self, command: _BaseCommand, template_id: str, prompt: str) -> None:
        self.command = command
        self.template_ids = [template_id]
        self.prompts = [prompt] if prompt else []


def build_commands(
    template: Any,
    note: Note,
    indications: list[str] | None = None,
    skip_sections: tuple[str, ...] = (),
    lab_partner_id: str | None = None,
    use_preferred_lab: bool = True,
) -> list[Built]:
    """Build the SDK commands for a template's entries, ready to originate.

    ``indications`` (dot-stripped ICD-10 codes) become the diagnosis on every
    order that has a diagnosis field. ``skip_sections`` leaves out commands
    from those note sections. Lab orders use ``lab_partner_id``: its tests when
    the order has some for it, or just the lab when the order has none set up.
    Without one, ``use_preferred_lab`` uses the patient's preferred lab; the
    panel turns it off, since its Lab choice (which starts on the preferred
    lab) decides.
    """
    day = visit_day(note)
    entries = [entry for entry in (template.commands or []) if entry.get("schema_key") in CATALOG]
    if (
        lab_partner_id is None
        and use_preferred_lab
        and any(entry["schema_key"] == "labOrder" for entry in entries)
    ):
        lab_partner_id = preferred_lab_partner_id(getattr(note, "patient_id", None))
    questionnaires = resolve(
        {
            key
            for key in (
                key_for(entry["schema_key"], entry.get("questionnaire"))
                for entry in entries
                if needs_questionnaire(entry["schema_key"])
            )
            if key
        }
    )

    built: list[Built] = []
    for entry in template.commands or []:
        catalog_entry = CATALOG.get(entry.get("schema_key", ""))
        if catalog_entry is None:
            log.warning(f"Skipping unknown command {entry.get('schema_key')!r}")
            continue
        if SECTION_BY_COMMAND.get(entry["schema_key"]) in skip_sections:
            continue

        fields: dict[str, str] = {"note_uuid": str(note.id), "command_uuid": str(uuid4())}
        if needs_questionnaire(entry["schema_key"]):
            key = key_for(entry["schema_key"], entry.get("questionnaire"))
            questionnaire = questionnaires.get(key) if key else None
            if questionnaire is not None:
                fields["questionnaire_id"] = str(questionnaire.id)
            else:
                # Inserted without one, so the clinician can still pick it in the note.
                log.warning(f"Template {template.template_id}: no active questionnaire for {key}")
        command = catalog_entry.command_class(**fields)
        if "questionnaire_id" in fields and entry.get("answers"):
            # Answers make Canvas skip the questionnaire's own carry forward.
            command.answers = answers_for(command, entry["answers"])
        apply_form(command, entry.get("fields") or {}, day, lab_partner_id)
        # Carry forward wins over the form when the patient has a prior command.
        if (
            entry.get("carry_forward")
            and kind_of(template) == TEMPLATE
            and supports_carry_forward(command.Meta.key)
        ):
            command = _carry_forward(command, catalog_entry.command_class, note)
        if indications:
            set_indications(command, indications)
        set_note_provider(command, note)
        built.append(Built(command, template.template_id, (entry.get("scribe_prompt") or "").strip()))
    return built


def originate_effects(
    built: list[Built],
    secrets: dict[str, Any],
    replace_line: bool,
    mark_quickpicks: bool = False,
    template_tag: str | None = None,
) -> list[Effect]:
    """One batch origination, then each command's metadata.

    The batch runs first, so every command exists before its metadata is written.
    ``mark_quickpicks`` tags each command with the quickpicks it came from, which
    is how the panel knows a quickpick is already on the note. ``template_tag``
    tags each command with the template a visit's note type inserted, so a later
    change of visit type can tell those commands apart.
    """
    if not built:
        return []
    include_prompts = scribe_enabled(secrets)
    metadata: list[Effect] = []
    for item in built:
        if include_prompts and item.prompts:
            metadata.append(
                item.command.upsert_metadata(key=SCRIBE_PROMPT_METADATA_KEY, value="\n".join(item.prompts))
            )
        if mark_quickpicks:
            for template_id in item.template_ids:
                metadata.append(
                    item.command.upsert_metadata(key=f"{QUICKPICK_MARKER_PREFIX}{template_id}", value="1")
                )
        if template_tag:
            metadata.append(item.command.upsert_metadata(key=TEMPLATE_COMMAND_KEY, value=template_tag))
    return [
        BatchOriginateCommandEffect(
            commands=[item.command for item in built], replace_line=replace_line
        ).apply(),
        *metadata,
    ]


def template_effects(
    template: Any,
    note: Note,
    secrets: dict[str, Any],
    replace_line: bool,
    indications: list[str] | None = None,
    skip_sections: tuple[str, ...] = (),
) -> list[Effect]:
    """Return the batch origination plus any scribe-prompt metadata for ``template``.

    ``replace_line`` puts the commands on the "/" trigger line; otherwise they
    are appended to the note. A quickpick's command is marked with it, wherever
    it is added from, so the panel shows it as already on the note.
    """
    return originate_effects(
        build_commands(template, note, indications, skip_sections),
        secrets,
        replace_line,
        mark_quickpicks=kind_of(template) == QUICKPICK,
    )


# Command metadata naming the template a note type inserted a command from.
TEMPLATE_COMMAND_KEY = "charting_tools:from_template"

# Command metadata key prefix naming the quickpick a command came from.
QUICKPICK_MARKER_PREFIX = "charting_tools:quickpick:"


def merge_lab_orders(built: list[Built]) -> list[Built]:
    """Fold every lab order for the same lab partner into one requisition.

    Tests are combined in order, the draw is fasting when any test needs it,
    comments and indications are joined, and the merged command remembers every
    quickpick it came from. Other commands pass through unchanged.
    """
    merged: list[Built] = []
    by_partner: dict[str, Built] = {}
    for item in built:
        command = item.command
        if command.Meta.key != "labOrder":
            merged.append(item)
            continue
        partner = str(command.lab_partner or "")
        target = by_partner.get(partner)
        if target is None:
            by_partner[partner] = item
            merged.append(item)
            continue
        lab = target.command
        lab.tests_order_codes = _union(lab.tests_order_codes, command.tests_order_codes)
        lab.diagnosis_codes = _union(lab.diagnosis_codes, command.diagnosis_codes)
        if command.fasting_required:
            lab.fasting_required = True
        comments = [c for c in (lab.comment, command.comment) if c]
        if comments:
            lab.comment = "; ".join(_union(comments[:1], comments[1:]))[:LAB_COMMENT_LIMIT]
        target.template_ids.extend(item.template_ids)
        target.prompts.extend(p for p in item.prompts if p not in target.prompts)
    return merged


def _union(first: list[str] | None, second: list[str] | None) -> list[str]:
    out = list(first or [])
    for value in second or []:
        if value not in out:
            out.append(value)
    return out


def visit_day(note: Note) -> date:
    """The day relative form dates count from: the note's date of service."""
    service = getattr(note, "datetime_of_service", None)
    return service.date() if isinstance(service, datetime) else date.today()


def set_note_provider(command: Any, note: Any) -> None:
    """Make the note's provider the command's ordering provider or prescriber.

    Without one, an order a plugin creates is attributed to the plugin's own
    user. A provider the template's form already set is kept. (Assigned field
    by field: the sandbox has no setattr.)
    """
    provider = getattr(note, "provider", None)
    if provider is None:
        return
    if hasattr(command, "ordering_provider_key") and not command.ordering_provider_key:
        command.ordering_provider_key = str(provider.id)
    if hasattr(command, "prescriber_id") and not command.prescriber_id:
        command.prescriber_id = str(provider.id)


def set_indications(command: Any, codes: list[str]) -> None:
    """Put the charted diagnosis on whichever indication field the command has."""
    key = command.Meta.key
    if key in ("labOrder", "imagingOrder", "refer", "orderDme"):
        command.diagnosis_codes = list(codes)
    elif key == "prescribe":
        command.icd10_codes = list(codes)[:MAX_PRESCRIPTION_INDICATIONS]


def _carry_forward(
    command: _BaseCommand, command_class: Callable[..., _BaseCommand], note: Note
) -> _BaseCommand:
    """Return ``command`` prefilled from the prior note, or a fresh empty copy on failure."""
    previous = find_previous_command(note, command.Meta.key)
    if previous is None:
        return command
    try:
        apply_carry_forward(command, previous)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        # A prior command whose stored data has an unexpected shape still
        # gets its command inserted, just empty, rather than failing the template.
        # The error type only: a validation message can quote the prior note's text.
        log.warning(
            f"Could not carry forward {command.Meta.key} from command {previous.id}: {exc.__class__.__name__}"
        )
        return command_class(note_uuid=command.note_uuid, command_uuid=command.command_uuid)
    return command


# Note metadata marking a note that already received a template automatically.
# A rescheduled appointment reuses its note, so without it the template would
# be inserted again.
APPLIED_METADATA_KEY = "charting_tools:applied_template"

# The marker's value for a visit booked with a note type that has no template,
# so a later visit-type change knows there is nothing to swap out.
NO_TEMPLATE = "none"


def auto_apply(
    note: Note, note_type_identifier: str, secrets: dict[str, Any], mark_untemplated: bool = False
) -> list[Effect]:
    """Append the template assigned to ``note_type_identifier``, once per note.

    ``mark_untemplated`` (at booking) marks a note whose visit type has no
    template with ``NO_TEMPLATE``, so changing the visit type to one with a
    template later brings that template in.
    """
    # Only note templates carry note types (a NULL kind is a template saved before kinds).
    templates = NoteTemplate.objects.filter(active=True).exclude(kind__in=NON_TEMPLATE_KINDS).order_by("name")
    template = template_for_note_type(templates, note_type_identifier)
    if template is None and not mark_untemplated:
        return []
    if NoteMetadata.objects.filter(note_id=note.dbid, key=APPLIED_METADATA_KEY).exists():
        log.info(f"Note {note.id} already has a template applied; skipping")
        return []
    if template is None:
        return [NoteEffect(instance_id=str(note.id)).upsert_metadata(key=APPLIED_METADATA_KEY, value=NO_TEMPLATE)]

    effects = originate_effects(
        build_commands(template, note), secrets, replace_line=False, template_tag=template.template_id
    )
    if not effects:
        return []
    log.info(f"Applying note template {template.template_id} to note {note.id}")
    marker = NoteEffect(instance_id=str(note.id)).upsert_metadata(
        key=APPLIED_METADATA_KEY, value=template.template_id
    )
    return [*effects, marker]


def lab_partners_of(template: Any) -> list[dict[str, str]]:
    """The lab partners a template's lab orders have tests for, in order."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in template.commands or []:
        if entry.get("schema_key") != "labOrder":
            continue
        for variant in lab_variants(entry.get("fields") or {}):
            if not variant["tests"]:
                continue
            partner = variant["lab_partner"]
            if partner["id"] not in seen:
                seen.add(partner["id"])
                out.append(partner)
    return out
