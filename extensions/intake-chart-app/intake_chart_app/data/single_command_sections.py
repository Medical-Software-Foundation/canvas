"""Single-command section abstractions.

A 'single-command section' commits at most one Canvas command per intake
commit. Used for **Vitals** (blank pre-fill, eight numeric fields) and
**Social History** (questionnaire-backed StructuredAssessment).

Subclasses declare their field types via ``int_fields`` / ``float_fields`` /
``str_fields``; the base class handles emit-ready checks and form-payload →
command-kwarg coercion.
"""
from __future__ import annotations

from typing import Any, ClassVar

from canvas_sdk.commands import StructuredAssessmentCommand, VitalsCommand


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    return True


def _coerce_int(value: Any) -> int | None:
    """Round form-supplied numeric strings/floats to int. Returns None if the
    value is empty or unparseable so unparseable inputs get dropped rather
    than blowing up VitalsCommand's pydantic validator."""
    if not _has_value(value):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if not _has_value(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SingleCommandSection:
    """Base class. Subclasses set ``section_id``, ``command_class`` and the
    field-name tuples."""

    section_id: ClassVar[str]
    command_class: ClassVar[type]
    int_fields: ClassVar[tuple[str, ...]] = ()
    float_fields: ClassVar[tuple[str, ...]] = ()
    str_fields: ClassVar[tuple[str, ...]] = ()

    def all_fields(self) -> tuple[str, ...]:
        return self.int_fields + self.float_fields + self.str_fields

    def is_emit_ready(self, draft: dict[str, Any]) -> bool:
        return any(_has_value(draft.get(f)) for f in self.all_fields())

    def build_kwargs(self, draft: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for f in self.int_fields:
            i_val = _coerce_int(draft.get(f))
            if i_val is not None:
                kwargs[f] = i_val
        for f in self.float_fields:
            f_val = _coerce_float(draft.get(f))
            if f_val is not None:
                kwargs[f] = f_val
        for f in self.str_fields:
            s_val = draft.get(f)
            if _has_value(s_val):
                kwargs[f] = str(s_val).strip()
        return kwargs


class VitalsSection(SingleCommandSection):
    """Vitals — height, weight, BP, pulse, temperature, respiration, SpO2.

    Field names match VitalsCommand kwargs exactly so the form payload maps
    1:1 to the command. ``body_temperature`` is the lone float; everything
    else is int (per the SDK's pydantic validators)."""

    section_id = "vitals"
    command_class = VitalsCommand
    int_fields = (
        "height",
        "weight_lbs",
        "blood_pressure_systole",
        "blood_pressure_diastole",
        "pulse",
        "respiration_rate",
        "oxygen_saturation",
    )
    float_fields = (
        "body_temperature",
    )


class SocialHistorySection(SingleCommandSection):
    """ATOD social-history questionnaire.

    Unlike VitalsSection, the SDK command (``StructuredAssessmentCommand``)
    isn't keyed by per-attribute kwargs — it accepts a ``questionnaire_id``
    + ``result`` and exposes the per-question responses through
    ``cmd.questions[i].add_response(...)``. That makes the int/float/str-
    field model unusable here, so this subclass overrides ``is_emit_ready``
    and ``build_kwargs`` outright. The reconciler dispatch layer
    (``_commit_questionnaire_section`` in api/intake_api.py) consumes the
    ``answers`` dict returned by ``build_kwargs`` to walk ``cmd.questions``
    and emit the originate+edit (or edit-only) pair."""

    section_id = "social_history"
    command_class = StructuredAssessmentCommand
    questionnaire_code: ClassVar[str] = "INTAKE_ATOD_V1"

    # The four question codes from the bundled YAML, in form-field-id order.
    _form_field_to_question_code: ClassVar[dict[str, str]] = {
        "alcohol": "INTAKE_ATOD_ALCOHOL",
        "tobacco": "INTAKE_ATOD_TOBACCO",
        "drugs": "INTAKE_ATOD_DRUGS",
        "details": "INTAKE_ATOD_DETAILS",
    }

    def is_emit_ready(self, draft: dict[str, Any]) -> bool:
        return any(
            _has_value(draft.get(field_id))
            for field_id in self._form_field_to_question_code
        )

    def build_kwargs(self, draft: dict[str, Any]) -> dict[str, Any]:
        answers: dict[str, str] = {}
        for field_id, question_code in self._form_field_to_question_code.items():
            value = draft.get(field_id)
            if not _has_value(value):
                continue
            answers[question_code] = str(value).strip()
        return {"answers": answers}


SECTIONS: list[SingleCommandSection] = [
    VitalsSection(),
    SocialHistorySection(),
]
