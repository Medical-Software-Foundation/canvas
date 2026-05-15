"""Multi-command section abstractions.

A 'multi-command section' commits 0..N Canvas commands per intake commit, one
batch per row in the draft. Active-list sections (Problems, Allergies,
Medications) support add / edit / remove per row; append-only history sections
support add only.

Each row in the section's draft has the shape::

    {
        "action": "confirm" | "edit" | "remove" | "add",
        "values": {...field-id: value},
    }

The reconciler walks the draft rows alongside the AttributeHub-recorded
``prior_map`` (``row_id -> command_uuid``), dispatches each row to the
subclass-specific add/edit/remove logic, and returns the effects list +
the new ``row_id -> command_uuid`` map to persist.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, ClassVar

from canvas_sdk.commands.commands.allergy import Allergen, AllergenType

from canvas_sdk.commands import (
    AllergyCommand,
    DiagnoseCommand,
    FamilyHistoryCommand,
    MedicalHistoryCommand,
    MedicationStatementCommand,
    PastSurgicalHistoryCommand,
    RemoveAllergyCommand,
    ResolveConditionCommand,
    StopMedicationCommand,
)


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    return True


class RowOutcome:
    """One row's contribution to the commit batch.

    - ``effects``: list of Canvas Effect instances to apply.
    - ``map_uuid``: command_uuid to record at ``new_map[row_id]`` after this
      commit. ``None`` means "do not write a fresh entry".
    - ``keep_prior_in_map``: when ``True`` and a ``prior_uuid`` exists, copy
      it into ``new_map[row_id]``. Used for Confirm where there's nothing to
      emit but the existing mapping should survive.

    Implemented as a plain class (not ``@dataclass``) because Canvas's
    RestrictedPython sandbox doesn't expose plugin modules in ``sys.modules``
    the way ``dataclasses._process_class`` expects when introspecting field
    types — using ``@dataclass`` here raises ``AttributeError: 'NoneType' has
    no attribute '__dict__'`` at module-load time.
    """

    def __init__(
        self,
        effects: list[Any] | None = None,
        map_uuid: str | None = None,
        keep_prior_in_map: bool = False,
    ) -> None:
        self.effects: list[Any] = effects if effects is not None else []
        self.map_uuid = map_uuid
        self.keep_prior_in_map = keep_prior_in_map


class MultiCommandSection:
    """Base class for multi-command sections.

    Subclasses override ``_add``, ``_edit``, and ``_remove`` to encode the
    section-specific command policy. The base class handles row dispatch,
    confirm semantics, and assembling the new map.
    """

    section_id: ClassVar[str]

    def reconcile(
        self,
        note_uuid: str,
        draft_rows: dict[str, dict[str, Any]],
        prior_map: dict[str, str],
    ) -> tuple[list[Any], dict[str, str]]:
        effects: list[Any] = []
        new_map: dict[str, str] = {}
        for row_id, row in (draft_rows or {}).items():
            if not row_id:
                continue
            payload = row if isinstance(row, dict) else {}
            action = (payload.get("action") or "confirm").lower()
            raw_values = payload.get("values")
            values: dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
            prior_uuid = prior_map.get(row_id)
            outcome = self._dispatch(
                note_uuid=note_uuid,
                action=action,
                row_id=row_id,
                values=values,
                prior_uuid=prior_uuid,
            )
            effects.extend(outcome.effects)
            if outcome.map_uuid:
                new_map[row_id] = outcome.map_uuid
            elif outcome.keep_prior_in_map and prior_uuid:
                new_map[row_id] = prior_uuid
        return effects, new_map

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        *,
        note_uuid: str,
        action: str,
        row_id: str,
        values: dict[str, Any],
        prior_uuid: str | None,
    ) -> RowOutcome:
        if action == "confirm":
            # Confirm is a no-op; preserve any existing map entry so a row
            # that's been committed before doesn't get re-originated next time.
            return RowOutcome(keep_prior_in_map=True)
        if action == "add":
            return self._add(note_uuid, row_id, values, prior_uuid)
        if action == "edit":
            return self._edit(note_uuid, row_id, values, prior_uuid)
        if action == "remove":
            return self._remove(note_uuid, row_id, values, prior_uuid)
        # Unknown action — treat as confirm (no-op), preserve mapping.
        return RowOutcome(keep_prior_in_map=True)

    # ------------------------------------------------------------------
    # Subclass hooks — override these per section
    # ------------------------------------------------------------------

    def _add(
        self,
        note_uuid: str,
        row_id: str,
        values: dict[str, Any],
        prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError

    def _edit(
        self,
        note_uuid: str,
        row_id: str,
        values: dict[str, Any],
        prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError

    def _remove(
        self,
        note_uuid: str,
        row_id: str,
        values: dict[str, Any],
        prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stripped(values: dict[str, Any], key: str) -> str:
    v = values.get(key)
    return str(v).strip() if v is not None else ""


def _chart_row_id(row_id: str, prefix: str) -> str:
    """Strip the section's prefix off ``row_id`` to get the underlying chart
    row's UUID. Pre-filled rows are keyed e.g. ``condition:<uuid>`` so the
    UUID for ResolveConditionCommand etc. is the suffix."""
    if row_id.startswith(prefix + ":"):
        return row_id[len(prefix) + 1:]
    return row_id


SNOMED_SYSTEM = "http://snomed.info/sct"
UNSTRUCTURED_SYSTEM = "UNSTRUCTURED"


def _unstructured_coding(
    values: dict[str, Any], code_field: str
) -> dict[str, Any] | None:
    """Build a Coding dict with ``system="UNSTRUCTURED"`` for ICD-10 picks
    bound for commands whose condition field is typed ``str | Coding``
    (``PastSurgicalHistoryCommand.past_surgical_history`` and
    ``FamilyHistoryCommand.family_history``).

    Canvas's chart renderer treats those Coding-typed fields as
    structured codings: submitting a plain string leaves the chart row
    blank, while a Coding dict renders the ``display`` value. The SDK
    validators on both commands explicitly allow ``UNSTRUCTURED`` as a
    code system, so a free-text ICD-10 picker can ride through as
    ``{"system": "UNSTRUCTURED", "code": "<icd10>", "display":
    "<name>"}``.

    ``MedicalHistoryCommand.past_medical_history`` is typed plain
    ``str | None`` and renders the bare string correctly — callers
    there should use :func:`_icd10_freetext` instead.
    """
    code = _stripped(values, code_field)
    if not code:
        return None
    display = _stripped(values, code_field + "__display")
    return {
        "system": UNSTRUCTURED_SYSTEM,
        "code": code,
        "display": display or code,
    }


def _snomed_payload(
    values: dict[str, Any], code_field: str
) -> dict[str, Any] | None:
    """Build the ``{system, code, display}`` dict that PMH / Surgical /
    Family SDK commands accept for SNOMED-coded fields.

    The picked code lives in ``values[code_field]``; the human-readable
    display name lives in the sibling ``<code_field>__display`` value
    written by intake.js's pick() handler. Returns ``None`` when no
    code is picked (caller short-circuits the row)."""
    code = _stripped(values, code_field)
    if not code:
        return None
    display = _stripped(values, code_field + "__display")
    return {"system": SNOMED_SYSTEM, "code": code, "display": display}


def _icd10_freetext(
    values: dict[str, Any], code_field: str
) -> str | None:
    """Return the picked ICD-10 entry's display name (or the code as a
    fallback) as a plain free-text string.

    The SDK history commands (``MedicalHistoryCommand``,
    ``PastSurgicalHistoryCommand``, ``FamilyHistoryCommand``) accept ``str``
    for their condition fields but their validators only allow SNOMED /
    UNSTRUCTURED Coding dicts — so ICD-10 picks have to ride through as
    strings. The shape that renders correctly on the chart is
    ``past_medical_history=<display name>`` (or the ICD-10 code as a
    fallback when the display name is unavailable); appending the code as
    a parenthesised suffix (``"<display> (<code>)"``) breaks Canvas's
    chart renderer — the value shows up blank because the renderer tries
    to parse the trailing "(CODE)" as a code lookup.

    Returns ``None`` when no code is picked so callers can short-circuit
    the row entirely.
    """
    code = _stripped(values, code_field)
    if not code:
        return None
    display = _stripped(values, code_field + "__display")
    return display or code


def _parse_date(raw: str | None) -> date | None:
    """HTML5 ``<input type="date">`` emits ``YYYY-MM-DD``. ``date.fromisoformat``
    accepts exactly that. Garbage / empty inputs return ``None`` so the
    caller skips the field entirely instead of crashing."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None


def _allergen_from_compound(raw: str) -> Allergen | None:
    """Parse the ``"<concept_id>|<concept_type>"`` compound code produced by
    the /intake/search/allergy proxy into an ``Allergen`` TypedDict.
    Returns ``None`` if the value is missing or malformed so callers can
    early-out the row."""
    if not raw or "|" not in raw:
        return None
    cid_str, ctype_str = raw.split("|", 1)
    try:
        return Allergen(
            concept_id=int(cid_str),
            concept_type=AllergenType(int(ctype_str)),
        )
    except (ValueError, KeyError):
        return None


def _allergy_severity(raw: str) -> AllergyCommand.Severity | None:
    """Map the select-input string ("mild" / "moderate" / "severe") to the
    SDK's Severity enum. Returns ``None`` for empty / unknown values."""
    if not raw:
        return None
    try:
        return AllergyCommand.Severity(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Concrete sections
# ---------------------------------------------------------------------------


PROBLEMS_ROW_PREFIX = "condition"
ALLERGIES_ROW_PREFIX = "allergy"
MEDICATIONS_ROW_PREFIX = "medication"
NEW_ROW_PREFIX = "new"

DEFAULT_EDIT_NARRATIVE = "Updated during intake review"
DEFAULT_REMOVE_RATIONALE = "Reviewed during intake — patient confirms no longer active"


class ProblemsSection(MultiCommandSection):
    """Problems active-list — Diagnose / ResolveCondition.

    - Add → ``DiagnoseCommand``: requires ``icd10_code``; ``background`` optional.
    - Remove (UI label "Resolve") → ``ResolveConditionCommand``: takes the
      original Condition's ``condition_id`` (== row_id sans prefix) plus a
      rationale.
    - Edit was dropped from the UI in UAT — ``UpdateDiagnosisCommand`` was
      unreliable on the target Canvas instance, so Resolve + Add new is the
      supported workflow.
    """

    section_id = "problems"

    def _add(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        icd10_code = _stripped(values, "icd10_code")
        if not icd10_code:
            return RowOutcome()
        kwargs: dict[str, Any] = {"icd10_code": icd10_code}
        background = _stripped(values, "background")
        if background:
            kwargs["background"] = background
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = DiagnoseCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        # Edit affordance was dropped from the Problems UI in UAT —
        # UpdateDiagnosisCommand was unreliable on the target Canvas
        # instance, so Resolve + Add new is the supported workflow. This
        # no-op absorbs stale drafts that ride through with action="edit".
        return RowOutcome()

    def _remove(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        condition_id = _chart_row_id(row_id, PROBLEMS_ROW_PREFIX)
        if not condition_id:
            return RowOutcome()
        rationale = _stripped(values, "rationale") or DEFAULT_REMOVE_RATIONALE
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = ResolveConditionCommand(
            note_uuid=note_uuid,
            command_uuid=cmd_uuid,
            condition_id=condition_id,
            rationale=rationale,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)


class AllergiesSection(MultiCommandSection):
    """Allergies active-list — Allergy / RemoveAllergy.

    No in-place edit command exists in the SDK, so Edit = RemoveAllergy(old) +
    Allergy(new). The new map entry records the *new* AllergyCommand's
    command_uuid (so a subsequent Remove targets the new command, not the
    pre-existing chart row that's already been removed).
    """

    section_id = "allergies"

    def _add(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        allergen = _allergen_from_compound(_stripped(values, "allergen_code"))
        if allergen is None:
            return RowOutcome()
        kwargs: dict[str, Any] = {"allergy": allergen}
        severity = _allergy_severity(_stripped(values, "severity"))
        if severity is not None:
            kwargs["severity"] = severity
        narrative = _stripped(values, "narrative")
        if narrative:
            kwargs["narrative"] = narrative
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = AllergyCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        # Edit was a remove+recreate workaround (AllergyCommand has no native
        # in-place edit). Dropped in UAT because the affordance was confusing
        # and partially broken — the Remove + Add new pair covers the same
        # workflow with fewer surprises. The UI no longer surfaces an Edit
        # button on Allergies rows; defensively short-circuit here in case a
        # stale draft somehow rides through with action="edit".
        return RowOutcome()

    def _remove(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        allergy_id = _chart_row_id(row_id, ALLERGIES_ROW_PREFIX)
        if not allergy_id:
            return RowOutcome()
        narrative = _stripped(values, "narrative") or DEFAULT_REMOVE_RATIONALE
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = RemoveAllergyCommand(
            note_uuid=note_uuid,
            command_uuid=cmd_uuid,
            allergy_id=allergy_id,
            narrative=narrative,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)


class MedicationsSection(MultiCommandSection):
    """Medications active-list — MedicationStatement / StopMedication.

    Same edit-as-replace shape as Allergies: no in-place statement-edit
    command exists, so Edit = StopMedication(old) + new MedicationStatement.
    """

    section_id = "medications"

    def _add(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        fdb_code = _stripped(values, "fdb_code")
        if not fdb_code:
            return RowOutcome()
        kwargs: dict[str, Any] = {"fdb_code": fdb_code}
        sig = _stripped(values, "sig")
        if sig:
            kwargs["sig"] = sig
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = MedicationStatementCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        # Edit was a stop+recreate workaround (MedicationStatementCommand has
        # no native in-place edit). Dropped in UAT — in practice the
        # affordance emitted only StopMedicationCommand because the search
        # widget's value wasn't being captured in the edit panel, which read
        # as a buggy "edit triggers stop". Remove + Add new is the supported
        # workflow now; this no-op guards against a stale draft riding
        # through with action="edit".
        return RowOutcome()

    def _remove(self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None) -> RowOutcome:
        medication_id = _chart_row_id(row_id, MEDICATIONS_ROW_PREFIX)
        if not medication_id:
            return RowOutcome()
        rationale = _stripped(values, "rationale") or DEFAULT_REMOVE_RATIONALE
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = StopMedicationCommand(
            note_uuid=note_uuid,
            command_uuid=cmd_uuid,
            medication_id=medication_id,
            rationale=rationale,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)


class MedicalHistorySection(MultiCommandSection):
    """Past Medical History — Add-only section.

    Originates ``MedicalHistoryCommand`` for each new entry. The picked
    ICD-10 concept is submitted as plain ``"<display> (<code>)"`` free
    text via ``_icd10_freetext`` — ``MedicalHistoryCommand``'s validator
    only accepts SNOMED / UNSTRUCTURED Coding dicts, so ICD-10 picks
    can't ride through as a Coding. Optional approximate dates and
    comments come through if the MA filled them. Edit and Remove are
    intentionally not implemented for this section — pre-filled chart
    rows stay read-only."""

    section_id = "medical_history"

    def _add(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        condition_text = _icd10_freetext(values, "medical_history_code")
        if condition_text is None:
            return RowOutcome()
        kwargs: dict[str, Any] = {"past_medical_history": condition_text}
        start_date = _parse_date(_stripped(values, "approximate_start_date"))
        if start_date is not None:
            kwargs["approximate_start_date"] = start_date
        end_date = _parse_date(_stripped(values, "approximate_end_date"))
        if end_date is not None:
            kwargs["approximate_end_date"] = end_date
        comments = _stripped(values, "comments")
        if comments:
            kwargs["comments"] = comments
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = MedicalHistoryCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("MedicalHistorySection is Add-only")

    def _remove(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("MedicalHistorySection is Add-only")


class SurgicalHistorySection(MultiCommandSection):
    """Surgical & Procedure History — Add-only section.

    Originates ``PastSurgicalHistoryCommand`` for each new entry. ICD-10
    picks submit as an UNSTRUCTURED Coding dict via
    :func:`_unstructured_coding` — ``past_surgical_history`` is typed
    ``str | Coding`` and Canvas's chart renderer treats the field as a
    structured coding (a plain string renders blank). Optional
    approximate date and comment come through if the MA filled them."""

    section_id = "surgical_history"

    def _add(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        procedure_coding = _unstructured_coding(values, "surgical_history_code")
        if procedure_coding is None:
            return RowOutcome()
        kwargs: dict[str, Any] = {"past_surgical_history": procedure_coding}
        approx_date = _parse_date(_stripped(values, "approximate_date"))
        if approx_date is not None:
            kwargs["approximate_date"] = approx_date
        comment = _stripped(values, "comment")
        if comment:
            kwargs["comment"] = comment
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = PastSurgicalHistoryCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("SurgicalHistorySection is Add-only")

    def _remove(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("SurgicalHistorySection is Add-only")


class FamilyHistorySection(MultiCommandSection):
    """Family History — Add-only section.

    Originates ``FamilyHistoryCommand`` for each new entry. ``relative``
    is required (matches the chart sidebar: rows without a relative are
    meaningless). ICD-10 picks for ``family_history`` submit as an
    UNSTRUCTURED Coding dict via :func:`_unstructured_coding` —
    ``family_history`` is typed ``str | Coding`` and Canvas's chart
    renderer needs a structured coding to render the display. ``note``
    is optional. A row with just ``relative='Mother'`` is the "asked,
    nothing reported" pattern."""

    section_id = "family_history"

    def _add(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        relative = _stripped(values, "relative")
        if not relative:
            return RowOutcome()
        kwargs: dict[str, Any] = {"relative": relative}
        condition_coding = _unstructured_coding(values, "family_history_code")
        if condition_coding is not None:
            kwargs["family_history"] = condition_coding
        note = _stripped(values, "note")
        if note:
            kwargs["note"] = note
        cmd_uuid = prior_uuid or _new_uuid()
        cmd = FamilyHistoryCommand(
            note_uuid=note_uuid, command_uuid=cmd_uuid, **kwargs,
        )
        effect = cmd.edit() if prior_uuid else cmd.originate()
        return RowOutcome(effects=[effect], map_uuid=cmd_uuid)

    def _edit(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("FamilyHistorySection is Add-only")

    def _remove(
        self, note_uuid: str, row_id: str, values: dict[str, Any], prior_uuid: str | None,
    ) -> RowOutcome:
        raise NotImplementedError("FamilyHistorySection is Add-only")


SECTIONS: list[MultiCommandSection] = [
    ProblemsSection(),
    AllergiesSection(),
    MedicationsSection(),
    MedicalHistorySection(),
    SurgicalHistorySection(),
    FamilyHistorySection(),
]
