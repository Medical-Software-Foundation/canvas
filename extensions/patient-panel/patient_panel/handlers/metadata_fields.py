"""Generic patient-metadata additional-fields handler.

Reads the `METADATA_FIELDS` secret (JSON list) and emits a
PatientMetadataCreateFormEffect describing the additional fields to show on
the patient-profile form. Generalizes Brigade's hardcoded handler.

Secret shape:
    [
        {
            "key": "risk_score",
            "label": "Risk Score",
            "type": "SELECT",          # TEXT | SELECT | DATE
            "required": false,         # optional, default false
            "editable": true,          # optional, default true (false → read-only)
            "options": ["Low", ...]    # required when type == SELECT
        },
        ...
    ]
"""

from __future__ import annotations

import json
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import (
    FormField,
    InputType,
    PatientMetadataCreateFormEffect,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

_INPUT_TYPES: dict[str, InputType] = {
    "TEXT": InputType.TEXT,
    "SELECT": InputType.SELECT,
    "DATE": InputType.DATE,
}


def _build_field(entry: dict[str, Any]) -> FormField | None:
    key = entry.get("key")
    if not isinstance(key, str) or not key:
        return None

    type_name = str(entry.get("type", "TEXT")).upper()
    input_type = _INPUT_TYPES.get(type_name)
    if input_type is None:
        return None

    label = entry.get("label") or key
    required = bool(entry.get("required", False))
    editable = bool(entry.get("editable", True))

    kwargs: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": input_type,
        "required": required,
        "editable": editable,
    }

    if input_type is InputType.SELECT:
        options = entry.get("options") or []
        if not isinstance(options, list):
            return None
        kwargs["options"] = [str(o) for o in options]

    return FormField(**kwargs)


class PatientMetadataFields(BaseHandler):
    """Emit form fields configured via the METADATA_FIELDS secret."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        raw = self.secrets.get("METADATA_FIELDS", "") if self.secrets else ""
        if not raw:
            return []

        try:
            config = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

        if not isinstance(config, list):
            return []

        fields: list[FormField] = []
        for entry in config:
            if not isinstance(entry, dict):
                continue
            field = _build_field(entry)
            if field is not None:
                fields.append(field)

        if not fields:
            return []

        return [PatientMetadataCreateFormEffect(form_fields=fields).apply()]
