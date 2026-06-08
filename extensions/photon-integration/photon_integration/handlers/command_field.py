"""Add the 'Send via Photon' field and filter transmission actions.

Mirrors the `documentation_only_prescription` reference: one handler renders the
field on the prescribe-family commands, and per-command handlers strip the
Canvas *send* / *sign & send* actions when the field is set so the prescription
is signed (triggering the Photon push) but never transmitted through Canvas.
"""

from __future__ import annotations

import json

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.command_metadata import (
    CommandMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import CommandMetadata

from photon_integration.command_payload import dispense_unit_text, resolve_dispense_unit
from photon_integration.constants import (
    ACTIONS_TO_REMOVE_WHEN_PHOTON,
    PHOTON_COMMAND_SCHEMA_KEYS,
    PHOTON_FIELD_KEY,
    PHOTON_FIELD_LABEL,
    PHOTON_FIELD_OPTIONS,
    PHOTON_FIELD_TRUE_VALUE,
)


def _photon_send_selected(command_id: str) -> bool:
    """True when the command's stored 'Send via Photon' value is the true value."""
    entry = CommandMetadata.objects.filter(
        command__id=command_id,
        key=PHOTON_FIELD_KEY,
    ).first()
    stored_value = (entry.value or "").strip() if entry else ""
    return stored_value == PHOTON_FIELD_TRUE_VALUE


class PhotonFieldHandler(BaseHandler):
    """Render the single-option 'Send via Photon' field on prescribe/refill/adjust."""

    RESPONDS_TO = EventType.Name(EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        if self.event.context.get("schema_key") not in PHOTON_COMMAND_SCHEMA_KEYS:
            return []

        return [
            CommandMetadataCreateFormEffect(
                command_uuid=self.event.target.id,
                form_fields=[
                    FormField(
                        key=PHOTON_FIELD_KEY,
                        label=PHOTON_FIELD_LABEL,
                        type=InputType.SELECT,
                        options=PHOTON_FIELD_OPTIONS,
                        required=False,
                        editable=True,
                    ),
                ],
            ).apply()
        ]


class _PhotonActionFilter(BaseHandler):
    """Base: remove send / sign&send actions when 'Send via Photon' is set."""

    def compute(self) -> list[Effect]:
        if not _photon_send_selected(self.event.target.id):
            return []

        actions = self.event.context.get("actions", [])
        filtered_actions = [
            action
            for action in actions
            if action.get("name") not in ACTIONS_TO_REMOVE_WHEN_PHOTON
        ]

        return [
            Effect(
                type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS,
                payload=json.dumps(filtered_actions),
            )
        ]


class PhotonPrescribeActionFilter(_PhotonActionFilter):
    """Filter actions on the Prescribe command."""

    RESPONDS_TO = EventType.Name(EventType.PRESCRIBE_COMMAND__AVAILABLE_ACTIONS)


class PhotonRefillActionFilter(_PhotonActionFilter):
    """Filter actions on the Refill command."""

    RESPONDS_TO = EventType.Name(EventType.REFILL_COMMAND__AVAILABLE_ACTIONS)


class PhotonAdjustPrescriptionActionFilter(_PhotonActionFilter):
    """Filter actions on the Adjust Prescription command."""

    RESPONDS_TO = EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__AVAILABLE_ACTIONS)


def _pharmacy_selected(fields: dict) -> bool:
    """True when a pharmacy is chosen on the command."""
    pharmacy = fields.get("pharmacy")
    if isinstance(pharmacy, str):
        return bool(pharmacy.strip())
    if isinstance(pharmacy, dict):
        return any(pharmacy.values())
    return bool(pharmacy)


class PhotonCommandValidation(BaseHandler):
    """Block commit of a 'Send via Photon' command when it can't be honored by
    Photon: an unmappable dispense unit, or a selected pharmacy (Photon routes to
    the patient's Photon pharmacy, so a Canvas pharmacy would be ignored)."""

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION),
    ]

    def compute(self) -> list[Effect]:
        if not _photon_send_selected(self.event.target.id):
            return []

        fields = self.event.context.get("fields") or {}
        messages: list[str] = []

        # Only flag a present-but-unmappable unit; a missing unit is Canvas's own
        # required-field validation, not ours.
        unit_text = dispense_unit_text(fields)
        if unit_text and resolve_dispense_unit(unit_text) is None:
            messages.append(
                f"Send via Photon: '{unit_text}' is not a valid Photon dispense unit. "
                "Choose a different quantity to dispense or uncheck Send via Photon."
            )

        if _pharmacy_selected(fields):
            messages.append(
                "Send via Photon: leave Pharmacy blank — the selected pharmacy is not "
                "sent to Photon (Photon routes to the patient's Photon pharmacy)."
            )

        if not messages:
            return []
        effect = CommandValidationErrorEffect()
        for message in messages:
            effect.add_error(message)
        return [effect.apply()]
