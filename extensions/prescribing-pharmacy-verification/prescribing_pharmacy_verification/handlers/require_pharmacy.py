from typing import Any

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class RequirePharmacyOnPrescription(BaseHandler):
    """Block Prescribe / Refill / Adjust-Prescription command commit unless a pharmacy is set.

    Each *_POST_VALIDATION event fires before the corresponding command is
    committed. Returning a CommandValidationErrorEffect with one or more errors
    prevents the commit and surfaces the message to the user in the Canvas UI.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION),
    ]

    ERROR_MESSAGE = "Select a pharmacy before recording."

    def compute(self) -> list[Effect]:
        fields: dict[str, Any] = self.event.context.get("fields") or {}
        pharmacy = fields.get("pharmacy")

        if self._has_pharmacy(pharmacy):
            return []

        effect = CommandValidationErrorEffect()
        effect.add_error(self.ERROR_MESSAGE)
        return [effect.apply()]

    @staticmethod
    def _has_pharmacy(pharmacy: Any) -> bool:
        """A pharmacy is considered set when its NCPDP ID is non-empty.

        The POST_VALIDATION context delivers `pharmacy` as a dict (or None when
        unset). Different Canvas versions have used `ncpdp_id`, `id`, or
        `value` for the identifier, so treat any non-empty string field as set.
        """
        if not pharmacy:
            return False
        if isinstance(pharmacy, str):
            return bool(pharmacy.strip())
        if isinstance(pharmacy, dict):
            for key in ("ncpdp_id", "id", "value"):
                v = pharmacy.get(key)
                if isinstance(v, str) and v.strip():
                    return True
            return False
        return False
