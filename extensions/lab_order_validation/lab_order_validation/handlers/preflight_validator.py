"""Pre-flight validation for lab orders bound for electronic transmission.

Hooks LAB_ORDER_COMMAND__POST_VALIDATION. Looks up the order's lab partner in
the LabPartner table; if its electronic_ordering_enabled flag is True, runs
five data-state checks. If any fail, returns a CommandValidationErrorEffect
that blocks Sign-and-Send and shows each error in the Canvas UI. For paper
or manual labs (or unknown partners), returns no effects.

The LabPartner lookup is the source of truth - we do not trust the field's
`extra.electronic_ordering_enabled` blob, because orders created by automation
may carry stale or missing extra data.

This is a hard block - there is no override. To send the order, the
underlying data must be fixed first.
"""

import re

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.coverage import Coverage
from canvas_sdk.v1.data.lab import LabPartner
from django.db.models import Prefetch
from logger import log

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$",
    re.IGNORECASE,
)

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
            f"note_uuid={note_uuid} lab_partner_field={lab_partner_field!r}"
        )

        partner = self._lookup_partner(lab_partner_field)
        is_electronic = bool(partner and partner.electronic_ordering_enabled)

        log.info(
            f"lab_order_validation: partner={self._partner_name(lab_partner_field)!r} "
            f"resolved={getattr(partner, 'name', None)!r} "
            f"electronic_ordering_enabled={getattr(partner, 'electronic_ordering_enabled', None)} "
            f"is_electronic={is_electronic}"
        )

        if not patient_id:
            return []

        if not is_electronic:
            return []

        # Prefetch the full coverage tree so the rule modules don't issue
        # N+1 queries when they iterate coverages -> issuer/subscriber -> addresses.
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
    def _lookup_partner(lab_partner_field) -> LabPartner | None:
        """Resolve the lab_partner field to a LabPartner record.

        The field can arrive in several shapes:
        - A dict from the UI dropdown: {"value": "<uuid or name>",
          "text": "<name>", "extra": {"electronic_ordering_enabled": bool}, ...}
        - A plain string from automation: the partner's name or UUID

        We try, in order:
        1. UUID lookup on any candidate that is UUID-shaped. The UUID_PATTERN
           gate prevents passing a non-UUID string to a UUIDField, which would
           otherwise raise ValidationError.
        2. Exact name match on every candidate.
        3. Case-insensitive name match on every candidate.

        Returns None only when no candidate matches. We deliberately do NOT
        catch unexpected exceptions (OperationalError, etc.) - those must
        propagate so they reach Sentry and the documented "hard block, no
        override" invariant remains observable in production. Swallowing
        them would fail-open and ship broken orders to Health Gorilla
        silently.
        """
        candidates: list[str] = []
        if isinstance(lab_partner_field, dict):
            for key in ("value", "text"):
                value = lab_partner_field.get(key)
                if isinstance(value, str) and value and value not in candidates:
                    candidates.append(value)
        elif isinstance(lab_partner_field, str) and lab_partner_field:
            candidates.append(lab_partner_field)

        if not candidates:
            log.info("lab_order_validation: no lab_partner identifier present")
            return None

        for candidate in candidates:
            if UUID_PATTERN.match(candidate):
                partner = LabPartner.objects.filter(id=candidate).first()
                if partner is not None:
                    log.info(
                        f"lab_order_validation: partner matched by id {candidate!r}"
                    )
                    return partner

        for candidate in candidates:
            partner = LabPartner.objects.filter(name=candidate).first()
            if partner is not None:
                log.info(
                    f"lab_order_validation: partner matched by name {candidate!r}"
                )
                return partner

        for candidate in candidates:
            partner = LabPartner.objects.filter(name__iexact=candidate).first()
            if partner is not None:
                log.info(
                    f"lab_order_validation: partner matched by case-insensitive "
                    f"name {candidate!r} -> {partner.name!r}"
                )
                return partner

        log.warning(
            f"lab_order_validation: no LabPartner matched any of {candidates!r}"
        )
        return None

    @staticmethod
    def _partner_name(lab_partner_field) -> str | None:
        if isinstance(lab_partner_field, dict):
            return lab_partner_field.get("text") or lab_partner_field.get("value")
        if isinstance(lab_partner_field, str):
            return lab_partner_field
        return None
