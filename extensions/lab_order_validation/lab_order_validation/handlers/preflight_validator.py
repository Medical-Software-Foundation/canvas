"""Pre-flight validation for lab orders bound for electronic transmission.

Hooks LAB_ORDER_COMMAND__POST_VALIDATION. When the selected lab partner has
electronic_ordering_enabled=True, runs five data-state checks. If any fail,
returns a CommandValidationErrorEffect that blocks Sign-and-Send and shows
each error in the Canvas UI. For paper or manual labs, returns no effects.

This is a hard block — there is no override. To send the order, the
underlying data must be fixed first.
"""

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.coverage import Coverage
from django.db.models import Prefetch
from logger import log

from lab_order_validation.rules.coverage_sequence import check as check_coverage_sequence
from lab_order_validation.rules.patient_address import check as check_patient_address
from lab_order_validation.rules.payer_completeness import check as check_payer_completeness
from lab_order_validation.rules.registration_update import check as check_registration_update
from lab_order_validation.rules.subscriber_address import check as check_subscriber_address


class LabOrderPreflightValidator(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.LAB_ORDER_COMMAND__POST_VALIDATION)

    def compute(self) -> list[Effect]:
        fields = self.event.context.get("fields") or {}
        patient_ctx = self.event.context.get("patient") or {}
        note_ctx = self.event.context.get("note") or {}

        patient_id = patient_ctx.get("id")
        note_uuid = note_ctx.get("uuid")
        lab_partner_field = fields.get("lab_partner")

        log.info(
            f"lab_order_validation: invoked patient_id={patient_id} "
            f"note_uuid={note_uuid} partner={self._partner_name(lab_partner_field)!r} "
            f"electronic={self._is_electronic(lab_partner_field)}"
        )

        if not patient_id:
            return []

        if not self._is_electronic(lab_partner_field):
            return []

        # Prefetch the full coverage tree so the rule modules don't issue
        # N+1 queries when they iterate coverages → issuer/subscriber → addresses.
        patient = (
            Patient.objects.filter(id=patient_id)
            .prefetch_related(
                "addresses",
                Prefetch(
                    "coverages",
                    queryset=Coverage.objects.select_related(
                        "issuer", "subscriber"
                    ).prefetch_related(
                        "issuer__addresses",
                        "issuer__phones",
                        "subscriber__addresses",
                    ),
                ),
            )
            .first()
        )
        if patient is None:
            log.info(f"lab_order_validation: patient {patient_id} not found, skipping")
            return []

        effect = CommandValidationErrorEffect()

        rule1_errors = check_coverage_sequence(patient)
        rule2_errors = check_registration_update(patient)
        rule3_errors = check_payer_completeness(patient)
        rule4_errors = check_patient_address(patient)
        rule5_errors = check_subscriber_address(patient)

        for message in rule1_errors:
            effect.add_error(message)
        for message in rule2_errors:
            effect.add_error(message)
        for message in rule3_errors:
            effect.add_error(message)
        for message in rule4_errors:
            effect.add_error(message)
        for message in rule5_errors:
            effect.add_error(message)

        log.info(
            f"lab_order_validation: rule results "
            f"rule1={len(rule1_errors)} rule2={len(rule2_errors)} "
            f"rule3={len(rule3_errors)} rule4={len(rule4_errors)} "
            f"rule5={len(rule5_errors)}"
        )

        if not effect.errors:
            return []

        log.info(
            f"lab_order_validation: BLOCKED Sign-and-Send patient={patient_id} "
            f"note={note_uuid} partner={self._partner_name(lab_partner_field)} "
            f"error_count={len(effect.errors)}"
        )
        return [effect.apply()]

    @staticmethod
    def _is_electronic(lab_partner_field) -> bool:
        """Read the electronic_ordering_enabled flag directly from the field.

        The lab_partner command field is a dropdown selection of shape:
            {"value": "<name>", "text": "<name>",
             "extra": {"electronic_ordering_enabled": bool}, ...}
        The flag is exposed in `extra` so we don't need a LabPartner lookup.
        """
        if not isinstance(lab_partner_field, dict):
            return False
        extra = lab_partner_field.get("extra") or {}
        return bool(extra.get("electronic_ordering_enabled"))

    @staticmethod
    def _partner_name(lab_partner_field) -> str | None:
        if not isinstance(lab_partner_field, dict):
            return None
        return lab_partner_field.get("text") or lab_partner_field.get("value")
