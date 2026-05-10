"""Phase D pass 2: registry of multi-command sections.

A multi-command section emits 0..N Canvas commands of the same class — one
per row entered by the dietician. Each row has a stable client-assigned
`row_id` so the server can reconcile add / edit / remove on resave:

    rows in payload, not in stored map  -> originate (mint command_uuid)
    rows in payload AND in stored map   -> edit in place (existing uuid)
    rows in stored map, not in payload  -> delete (drop the command)

The mapping `row_id -> command_uuid` lives on the AttributeHub under
`multi_commands:<section_id>` (a JSON dict). See `form_state.py`.

Pass-2 sections:

  - goals:                Goal command per goal
  - educational_materials: Instruct command per material (canonical + "other")
  - referrals:             Refer command per referral row
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from canvas_sdk.commands import GoalCommand, InstructCommand, ReferCommand
from canvas_sdk.commands.constants import CodeSystems, ServiceProvider
from canvas_sdk.v1.data import ServiceProvider as ServiceProviderRecord

# Header label shown on every Instruct command we emit for educational
# materials: "Instruct: Diet education / COMMENT: <material name>".
# Canvas renders `coding.code` as the visible title for UNSTRUCTURED-system
# Instruct commands (not `display`), so both fields carry the human label.
DIET_EDUCATION_CODING: dict[str, str] = {
    "system": CodeSystems.UNSTRUCTURED,
    "code": "Diet education",
    "display": "Diet education",
}


# ---- Goals ----------------------------------------------------------------

def _build_goal_kwargs(row: dict) -> dict[str, Any]:
    """One Goal command per row. The row's `goal_statement` text is the only
    field captured in pass 2 — priority/due-date can be added later."""
    text = (row.get("goal_statement") or "").strip()
    if not text:
        return {}
    return {"goal_statement": text}


def _goal_row_ready(row: dict) -> bool:
    return bool((row.get("goal_statement") or "").strip())


# ---- Educational materials -----------------------------------------------

# Canonical multi-select options confirmed with the customer (spec sec. 7).
# Each value doubles as the row_id stem so toggling the same material on/off
# keeps a stable identity across saves (e.g. row_id="material:dash_diet").
#
# PUBLIC CONTRACT — DO NOT RENAME WITHOUT A MIGRATION.
# These string keys are persisted as `material:<key>` row_ids inside saved
# AttributeHub form-state. Renaming a key here without a migration step
# orphans existing rows: the next save will treat the renamed material as a
# new row, originating a duplicate Instruct command and deleting the old one.
# See MIGRATIONS.md (added during OSS publication) for the rename procedure.
EDUCATIONAL_MATERIAL_OPTIONS: list[tuple[str, str]] = [
    ("dash_diet", "DASH diet"),
    ("mediterranean", "Mediterranean diet"),
    ("low_fodmap", "Low-FODMAP"),
    ("diabetic_carb_counting", "Diabetic carb counting"),
    ("weight_management", "Weight management"),
]
EDUCATIONAL_MATERIAL_LABELS: dict[str, str] = dict(EDUCATIONAL_MATERIAL_OPTIONS)


def _build_educational_material_kwargs(row: dict) -> dict[str, Any]:
    """Each selected material -> one Instruct command titled "Diet education"
    with the material name in the comment. The Instruct command's header is
    driven by `coding.display`; we use the SDK's UNSTRUCTURED system so we
    don't have to commit to a specific SNOMED code per material."""
    label = (row.get("name") or "").strip()
    if not label:
        return {}
    return {
        "coding": dict(DIET_EDUCATION_CODING),
        "comment": label,
    }


def _educational_material_row_ready(row: dict) -> bool:
    return bool((row.get("name") or "").strip())


# ---- Referrals -----------------------------------------------------------

def _resolve_enum(enum_cls: type[Enum], value: Any) -> Enum | None:
    """Map a posted form value back to its ReferCommand enum member.

    Pydantic accepts either the enum instance or its `.value` string, so we
    can be tolerant: lookups by `.name` (e.g. "ROUTINE") and by `.value`
    (e.g. "Routine") both work, and an unrecognized value is dropped so the
    field stays unset rather than raising a validation error."""
    if value is None or value == "":
        return None
    if isinstance(value, enum_cls):
        return value
    text = str(value).strip()
    for member in enum_cls:
        if member.value == text or member.name == text:
            return member
    return None


def _build_service_provider(row: dict) -> ServiceProvider | None:
    """Construct a ServiceProvider from the row's provider data.

    Prefers a resolved ServiceProvider DB record (`service_provider_id`
    set by the typeahead) and reads the canonical fields from there.
    Falls back to the four free-text fields when the dietician used the
    "add manually" affordance (e.g. the target isn't in the directory).

    All four pydantic fields (first_name/last_name/specialty/practice_name)
    are `required: str`, so we only emit a ServiceProvider when the
    chosen path supplies all four — a half-resolved record (e.g. an
    organization with no last_name, or one missing specialty) drops back
    to "no service_provider on this Refer command" and the dietician
    can fill missing pieces in Canvas's command UI.
    """
    sp_id = (row.get("service_provider_id") or "").strip()
    if sp_id:
        record = _lookup_service_provider(sp_id)
        if record is not None:
            first = (record.first_name or "").strip()
            last = (record.last_name or "").strip()
            specialty = (record.specialty or "").strip()
            practice = (record.practice_name or "").strip()
            if first and last and specialty and practice:
                return ServiceProvider(
                    first_name=first,
                    last_name=last,
                    specialty=specialty,
                    practice_name=practice,
                )

    first = (row.get("provider_first_name") or "").strip()
    last = (row.get("provider_last_name") or "").strip()
    specialty = (row.get("provider_specialty") or "").strip()
    practice = (row.get("provider_practice_name") or "").strip()
    if not (first and last and specialty and practice):
        return None
    return ServiceProvider(
        first_name=first,
        last_name=last,
        specialty=specialty,
        practice_name=practice,
    )


def _lookup_service_provider(sp_id: str) -> ServiceProviderRecord | None:
    try:
        return ServiceProviderRecord.objects.get(id=sp_id)
    except ServiceProviderRecord.DoesNotExist:
        return None


def _parse_indications(raw: Any) -> list[str]:
    """Indications arrive as a newline-separated textarea (each line is one
    ICD-10 code) or as a list when round-tripping form-state. Trim and
    drop blanks; preserve order so the dietician's intent stays intact."""
    if raw is None:
        return []
    if isinstance(raw, str):
        lines = raw.splitlines()
    elif isinstance(raw, (list, tuple)):
        lines = [str(x) for x in raw]
    else:
        return []
    out: list[str] = []
    for line in lines:
        code = line.strip()
        if code:
            out.append(code)
    return out


def _build_referral_kwargs(row: dict) -> dict[str, Any]:
    """Map a referral form row to Refer command kwargs. Primary input is
    `notes_to_specialist` (free text). Other fields fill in the rest of
    the Refer command: provider (ServiceProvider), indications (ICD-10
    list), clinical question + priority enums, internal comment,
    include-visit-note flag."""
    text = (row.get("notes_to_specialist") or "").strip()
    if not text:
        return {}

    kwargs: dict[str, Any] = {"notes_to_specialist": text}

    provider = _build_service_provider(row)
    if provider is not None:
        kwargs["service_provider"] = provider

    indications = _parse_indications(row.get("indications"))
    if indications:
        kwargs["diagnosis_codes"] = indications

    cq = _resolve_enum(ReferCommand.ClinicalQuestion, row.get("clinical_question"))
    if cq is not None:
        kwargs["clinical_question"] = cq

    priority = _resolve_enum(ReferCommand.Priority, row.get("priority"))
    if priority is not None:
        kwargs["priority"] = priority

    comment = (row.get("comment") or "").strip()
    if comment:
        kwargs["comment"] = comment

    include_visit_note = row.get("include_visit_note")
    if include_visit_note in (True, "true", "on", "1", 1, "yes"):
        kwargs["include_visit_note"] = True

    return kwargs


def _referral_row_ready(row: dict) -> bool:
    """A referral row only emits a Refer command when the three caller-
    visible required fields are filled: at least one indication, a clinical
    question, and the notes-to-specialist message. Provider info (typeahead
    or manual) is an enrichment — the form's UI surfaces these three with
    asterisks so the dietician sees what's required before clicking Save."""
    if not (row.get("notes_to_specialist") or "").strip():
        return False
    if not (row.get("clinical_question") or "").strip():
        return False
    if not _parse_indications(row.get("indications")):
        return False
    return True


# ---- Registry ------------------------------------------------------------

MULTI_COMMAND_SECTIONS: dict[str, dict[str, Any]] = {
    "goals": {
        "title": "Monitoring & Evaluation: Goals",
        "command_class": GoalCommand,
        # (field_id, label, kind) — drives front-end row rendering.
        "row_fields": [
            ("goal_statement", "Goal (as verbalized by patient)", "textarea"),
        ],
        "build_kwargs": _build_goal_kwargs,
        "is_row_ready": _goal_row_ready,
        "add_row_label": "Add another goal",
        "row_id_prefix": "goal",
    },
    "educational_materials": {
        "title": "Intervention: Educational Materials",
        "command_class": InstructCommand,
        "row_fields": [
            ("name", "Material", "text"),
        ],
        "build_kwargs": _build_educational_material_kwargs,
        "is_row_ready": _educational_material_row_ready,
        "add_row_label": "Add other material",
        "row_id_prefix": "material",
        # Pre-defined checklist choices rendered as fixed rows in addition to
        # the "add other" affordance. Keys here become `material:<key>` row_ids
        # so toggling stays stable across saves.
        "checklist_options": EDUCATIONAL_MATERIAL_OPTIONS,
        "checklist_field": "name",
    },
    "referrals": {
        "title": "Coordination of Care: Referrals",
        "command_class": ReferCommand,
        # Row fields use a 3-tuple `(field_id, label, kind)` for simple kinds
        # and a 4-tuple `(field_id, label, "select", options)` for dropdowns,
        # where `options` is a list of (value, label) pairs (with "" as a
        # sentinel for "not set"). The front-end renderer keys off `kind`.
        # Field order matches the Refer command's own field order in Canvas:
        # provider identity → clinical context → notes_to_specialist (the
        # message the recipient sees) → internal comment (notes the
        # patient/recipient won't see) → include-visit-note toggle.
        # The `indications` field uses kind="multiselect"; its options are
        # injected at render time from the patient's active PMH conditions
        # (see `_render_page`), so each referral's indications come from
        # the conditions actually on the chart.
        "row_fields": [
            # Typeahead-resolved DB ServiceProvider. When set, the save
            # handler reads canonical name/specialty/practice from the DB
            # record and ignores the four manual fields below. The label
            # field is hidden form-state used by the front-end to restore
            # the selected-chip display on tab reload.
            ("service_provider_id", "Refer to (search directory)", "provider_search"),
            ("service_provider_label", "", "hidden"),
            # Manual-entry fallback for ad-hoc providers not in the
            # directory. Used only when service_provider_id is empty.
            ("provider_first_name", "Provider first name (manual)", "text"),
            ("provider_last_name", "Provider last name (manual)", "text"),
            ("provider_specialty", "Provider specialty (manual)", "text"),
            ("provider_practice_name", "Provider practice name (manual)", "text"),
            ("indications", "Indications (select from active PMH) *", "multiselect"),
            (
                "clinical_question", "Clinical question *", "select",
                [
                    ("", "—"),
                    *[(m.value, m.value) for m in ReferCommand.ClinicalQuestion],
                ],
            ),
            (
                "priority", "Priority", "select",
                [
                    ("", "—"),
                    *[(m.value, m.value) for m in ReferCommand.Priority],
                ],
            ),
            ("notes_to_specialist", "Notes to specialist *", "textarea"),
            ("comment", "Internal comment", "textarea"),
            ("include_visit_note", "Include visit note", "checkbox"),
        ],
        "build_kwargs": _build_referral_kwargs,
        "is_row_ready": _referral_row_ready,
        "add_row_label": "Add another referral",
        "row_id_prefix": "ref",
        # Field IDs that must be filled before the front-end will let
        # the user submit the row. Mirrors `_referral_row_ready` so the
        # client-side gate matches the server-side gate exactly. The form
        # also marks these labels with " *".
        "required_fields": [
            "indications",
            "clinical_question",
            "notes_to_specialist",
        ],
    },
}


def get_section(section_id: str) -> dict[str, Any] | None:
    return MULTI_COMMAND_SECTIONS.get(section_id)


# Type alias mirroring single_command_sections.BuildKwargs but row-scoped.
BuildRowKwargs = Callable[[dict], dict[str, Any]]
