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


class PhotonDispenseUnitValidation(BaseHandler):
    """Block commit when 'Send via Photon' is set but the quantity-to-dispense
    unit can't be mapped to a Photon dispense unit (e.g. a packaging unit like
    a vial), so the provider fixes it before signing rather than at send time."""

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION),
    ]

    def compute(self) -> list[Effect]:
        if not _photon_send_selected(self.event.target.id):
            return []

        unit_text = dispense_unit_text(self.event.context.get("fields") or {})
        # Only flag a present-but-unmappable unit; a missing unit is Canvas's own
        # required-field validation, not ours.
        if not unit_text or resolve_dispense_unit(unit_text) is not None:
            return []

        effect = CommandValidationErrorEffect()
        effect.add_error(
            f"Send via Photon: '{unit_text}' is not a valid Photon dispense unit. "
            "Choose a different quantity to dispense or uncheck Send via Photon."
        )
        return [effect.apply()]
