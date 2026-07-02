"""Prescribe-family formulary & benefits workflow.

Three protocols cooperate across the Surescripts request/response cycle to show
real-time formulary coverage as custom HTML inside the command the prescriber
is editing. See ``prescribe_formulary_benefits.workflow`` for the data flow.
"""

from __future__ import annotations

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.surescripts.surescripts_messages import (
    SendSurescriptsBenefitsRequestEffect,
    SendSurescriptsEligibilityRequestEffect,
)
from canvas_sdk.events import EventType

# NOTE: only the eligibility wrapper is imported at module load. The benefits
# wrapper (`SurescriptsBenefitsResponse`) is imported lazily inside
# BenefitsResponseHandler so the plugin still loads — and the eligibility flow
# still works — on plugin-runner builds whose allowlist predates the benefits
# additions to canvas-plugins #1688. See [[project-plugin-package-layout]].
from canvas_sdk.events.surescripts import SurescriptsEligibilityResponse
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command

from logger import log

from prescribe_formulary_benefits.rendering import (
    render_benefits,
    render_error,
    render_loading,
    render_no_active_coverage,
    render_no_coverage,
    render_rejected,
)
from prescribe_formulary_benefits.workflow import (
    CACHE_TTL_SECONDS,
    COMMAND_CLASSES,
    command_kind_for_event,
    extract_medication,
    fingerprint_key,
    load_context,
    select_plan_name,
    store_context,
)


class PrescribeBenefitsTrigger(BaseProtocol):
    """Starts the workflow when a medication is selected in a prescribe-family command.

    Subscribes to the POST_UPDATE event for Prescribe, Refill, and Adjust
    Prescription. POST_UPDATE fires on every field change, so we de-duplicate on
    the chosen medication's NDC and only fire one eligibility request per
    (command, medication).
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_UPDATE),
        EventType.Name(EventType.REFILL_COMMAND__POST_UPDATE),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_UPDATE),
    ]

    def compute(self) -> list[Effect]:
        kind = command_kind_for_event(EventType.Name(self.event.type))
        if kind is None:
            return []

        command_uuid = str(self.event.target.id)
        fields = self.event.context.get("fields") or {}

        medication = extract_medication(fields)
        if medication is None:
            # Medication (or its dispensable NDC) not selected yet — nothing to do.
            return []
        description, ndc = medication

        cache = get_cache()
        if cache.get(fingerprint_key(command_uuid)) == ndc:
            # Already kicked off a lookup for this exact medication on this command.
            return []

        patient_id, staff_id = self._resolve_patient_and_staff(command_uuid)
        if not patient_id or not staff_id:
            log.info(
                "prescribe_formulary_benefits: missing patient/staff for command %s; skipping",
                command_uuid,
            )
            return []

        cache.set(fingerprint_key(command_uuid), ndc, timeout_seconds=CACHE_TTL_SECONDS)

        eligibility = SendSurescriptsEligibilityRequestEffect(
            patient_id=patient_id,
            staff_id=staff_id,
        )
        store_context(
            cache,
            eligibility.correlation_id,
            {
                "stage": "eligibility",
                "command_uuid": command_uuid,
                "command_kind": kind,
                "patient_id": patient_id,
                "staff_id": staff_id,
                "ndc": ndc,
                "description": description,
            },
        )

        command_cls = COMMAND_CLASSES[kind]
        loading = command_cls(command_uuid=command_uuid).set_custom_html(
            render_loading(description)
        )
        return [loading, eligibility.apply()]

    def _resolve_patient_and_staff(self, command_uuid: str) -> tuple[str | None, str | None]:
        """Resolve the command's patient and prescribing provider keys.

        The command event context carries the medication fields but not the
        patient/staff, so we read those from the persisted command and its note.
        """
        try:
            command = Command.objects.select_related("patient", "note", "note__provider").get(
                id=command_uuid
            )
        except Command.DoesNotExist:
            return None, None

        patient_id = command.patient.id if command.patient else None
        provider = command.note.provider if command.note else None
        staff_id = provider.id if provider else None
        return patient_id, staff_id


class EligibilityResponseHandler(BaseProtocol):
    """Receives the eligibility response and fires the benefits request.

    The eligibility response is where the patient's plan identity comes from;
    we pass that plan onto the benefits request for the chosen medication.
    """

    RESPONDS_TO = EventType.Name(EventType.SURESCRIPTS_ELIGIBILITY_RESPONSE)

    def compute(self) -> list[Effect]:
        response = SurescriptsEligibilityResponse.from_context(self.event.context)

        cache = get_cache()
        context = load_context(cache, response.correlation_id)
        if context is None or context.get("stage") != "eligibility":
            # Not a response to a request this plugin originated.
            return []

        command_cls = COMMAND_CLASSES[context["command_kind"]]
        command_uuid = context["command_uuid"]
        description = context["description"]

        if response.error:
            return [
                command_cls(command_uuid=command_uuid).set_custom_html(
                    render_error(description, response.error)
                )
            ]

        plans = response.plans
        active_plans = [p for p in plans if not p.rejected]
        log.info(
            "prescribe_formulary_benefits: eligibility returned %d plan(s), %d active",
            len(plans),
            len(active_plans),
        )

        if not plans:
            # No PBM on file or inactive coverage — both arrive as an empty list.
            return [
                command_cls(command_uuid=command_uuid).set_custom_html(
                    render_no_active_coverage(description)
                )
            ]

        if not active_plans:
            reasons = [p.reject_reason for p in plans if p.reject_reason]
            return [
                command_cls(command_uuid=command_uuid).set_custom_html(
                    render_rejected(description, reasons)
                )
            ]

        plan_name = select_plan_name(active_plans)
        if not plan_name:
            return [
                command_cls(command_uuid=command_uuid).set_custom_html(
                    render_no_active_coverage(description)
                )
            ]

        log.info(
            "prescribe_formulary_benefits: sending benefits request ndc=%s plan=%r",
            context["ndc"],
            plan_name,
        )
        benefits = SendSurescriptsBenefitsRequestEffect(
            patient_id=context["patient_id"],
            staff_id=context["staff_id"],
            medication_description=description,
            medication_ndc=context["ndc"],
            plan=plan_name,
        )
        store_context(cache, benefits.correlation_id, {**context, "stage": "benefits"})
        return [benefits.apply()]


class BenefitsResponseHandler(BaseProtocol):
    """Receives the benefits response and writes the formulary detail as custom HTML."""

    # Hardcoded event-name string (equivalent to
    # EventType.Name(EventType.SURESCRIPTS_BENEFITS_RESPONSE)) so class definition
    # doesn't depend on the benefits enum member existing on the runner.
    RESPONDS_TO = "SURESCRIPTS_BENEFITS_RESPONSE"

    def compute(self) -> list[Effect]:
        # Lazy import: on plugin-runner builds without the benefits wrapper this
        # handler still loads; it simply no-ops on the response instead of taking
        # the whole plugin (and the eligibility flow) down.
        try:
            from canvas_sdk.events.surescripts import SurescriptsBenefitsResponse
        except ImportError:
            log.warning(
                "prescribe_formulary_benefits: SurescriptsBenefitsResponse unavailable on this "
                "runner build; skipping benefits render."
            )
            return []

        response = SurescriptsBenefitsResponse.from_context(self.event.context)

        cache = get_cache()
        context = load_context(cache, response.correlation_id)
        if context is None or context.get("stage") != "benefits":
            return []

        command_cls = COMMAND_CLASSES[context["command_kind"]]
        command_uuid = context["command_uuid"]
        description = context["description"]

        log.info(
            "prescribe_formulary_benefits: benefits response error=%r ndc=%s coverages=%s",
            response.error,
            response.medication_ndc,
            [
                {
                    "pbm_name": c.pbm_name,
                    "formulary_status": c.formulary_status,
                    "prior_auth": c.prior_authorization_required,
                    "copays": len(c.copays),
                    "alternatives": len(c.alternatives),
                }
                for c in response.coverages
            ],
        )

        if response.error:
            html = render_error(description, response.error)
        else:
            html = render_benefits(description, response.coverages)

        return [command_cls(command_uuid=command_uuid).set_custom_html(html)]
