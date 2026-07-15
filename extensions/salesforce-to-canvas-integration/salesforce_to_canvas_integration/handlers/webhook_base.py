"""Shared plumbing for inbound Salesforce webhook handlers.

This module owns the pieces that every Salesforce inbound webhook needs to do
identically, HMAC verification, JSON payload parsing, record id validation,
idempotent dedup, and IncomingPatientRecord capture. Action-specific subclasses
inherit this base and only have to declare their route plus pick the action
label they capture under.
"""

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI
from canvas_sdk.utils.http import Http
from logger import log

from salesforce_to_canvas_integration.models import (
    IncomingPatientRecord,
    ResolutionAuditEntry,
    load_sync_settings,
)
from salesforce_to_canvas_integration.services.canvas_fhir_client import (
    CanvasFhirAuthError,
    CanvasFhirClient,
    CanvasFhirError,
    CanvasFhirNotConfiguredError,
    build_canvas_fhir_client,
)
from salesforce_to_canvas_integration.services.config import (
    ConfigError,
    PluginConfig,
    canvas_fhir_configured,
    load_config,
)
from salesforce_to_canvas_integration.services.effect_builder import (
    build_create_patient_effect,
    build_tag_deleted_effect,
    build_update_patient_effect,
)
from salesforce_to_canvas_integration.services.field_mapping import (
    MappedPatient,
    MappingError,
    map_record,
)
from salesforce_to_canvas_integration.services.hmac_verify import (
    SIGNATURE_HEADER,
    verify_signature,
)
from salesforce_to_canvas_integration.services.patient_link import (
    find_duplicate_patients,
    find_linked_patient_id,
)
from salesforce_to_canvas_integration.services.patient_snapshot import (
    canvas_demographics_by_id,
)
from salesforce_to_canvas_integration.services.resolution import (
    AUTOMATIC_ACTOR,
    write_resolution,
)
from salesforce_to_canvas_integration.services.storage import compute_entry_id
from salesforce_to_canvas_integration.services.sync_rules import (
    DELETE_ACTION_MARK_INACTIVE,
    DELETE_ACTION_TAG_DELETED,
    DELETE_ACTION_UNLINK,
    SyncFacts,
    SyncSettings,
    evaluate,
)

# Body intents carried by the deliberate sync. The Salesforce Canvas Sync field
# maps its value onto one of these, Sync to sync and Delete to delete. None on
# the Contact emits nothing at all.
INTENT_SYNC = "sync"
INTENT_DELETE = "delete"
_VALID_INTENTS = frozenset({INTENT_SYNC, INTENT_DELETE})

# Action labels written to IncomingPatientRecord.action. These are the vocabulary
# the admin console and the resolution routes already bucket on, so the intent is
# resolved down to one of these before capture rather than introducing a new one.
ACTION_CREATE = "create"
ACTION_MODIFY = "modify"
ACTION_DELETE = "delete"

# Resolution vocabulary the status API also writes. The automatic apply path
# resolves a row to the same status and action_taken values a human resolution
# would, so the Activity ledger and the Records buckets read an auto applied row
# exactly like a manual one, only the actor differs. See journal cnv-938/033 035.
_STATUS_ACCEPTED = "accepted"
_ACTION_TAKEN_CREATED = "created"
_ACTION_TAKEN_MODIFY_APPLIED = "modify_applied"
_ACTION_TAKEN_TAG_DELETED = "tag_deleted"
_ACTION_TAKEN_MARK_INACTIVE = "mark_inactive"
_ACTION_TAKEN_UNLINK = "unlink"

# The action_taken a skip writes, the hard gate that stands in for a never sync
# flag reads the newest decision for the contact against this. See cnv-938/029.
_ACTION_TAKEN_SKIPPED = "skipped"

# Hold reason written when a modify passes the filters but its linked patient
# cannot be resolved at apply time, the belt and suspenders for a link that
# vanished between deriving the action and applying it.
_REASON_MODIFY_LINK_LOST = "linked patient not found"

# Hold reasons written when an auto applied delete cannot reach Canvas FHIR. Mark
# inactive and unlink call the FHIR client synchronously, so a missing FHIR
# configuration or an auth or transport failure degrades the delete to a manual
# hold rather than failing the webhook, which always answers 202. These are
# webhook runtime reasons, not evaluator decisions, so they live here beside the
# modify link lost reason rather than in the evaluator's vocabulary.
_REASON_FHIR_NOT_CONFIGURED = "Canvas FHIR not configured"
_REASON_FHIR_DELETE_FAILED = "Canvas FHIR delete failed"


def _coerce_birthdate(value: Any) -> date | None:
    """Parse a mapped date_of_birth for the duplicate lookup query.

    Mirrors the writer's date coercion so the gate reads the same date the
    effect builder would write. Returns None when the value is absent or
    unparseable, in which case the duplicate gate simply does not fire.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class _HMACCredentials(Credentials):
    """Pulls the body and signature header off the request for HMAC verification."""

    def __init__(self, request: Any) -> None:
        super().__init__(request)
        self.body: bytes = request.body
        self.signature: str | None = request.headers.get(SIGNATURE_HEADER)


def _bad_request(message: str) -> Effect:
    return JSONResponse(
        content={"error": message},
        status_code=HTTPStatus.BAD_REQUEST,
    ).apply()


def _extract_record_id(record: dict[str, Any]) -> str | None:
    candidate = record.get("Id") or record.get("id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _map_typed_fields(
    record: dict[str, Any], field_mapping: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Best effort map of the record to the row's typed name fields.

    A malformed mapping does not reject the event. The row is still captured with
    raw_payload intact so the audit trail stays faithful and a reviewer can work
    from the full payload.
    """
    try:
        mapped = map_record(record, field_mapping)
    except MappingError as exc:
        log.warning("Salesforce webhook field mapping failed, capturing raw only: %s", exc)
        return {}
    fields = mapped.canvas_fields
    return {
        "first_name": str(fields.get("first_name") or ""),
        "last_name": str(fields.get("last_name") or ""),
        "email": str(fields.get("email") or ""),
        "phone": str(fields.get("phone") or ""),
    }


class SalesforceWebhookBase(SimpleAPI):
    """Shared plumbing for the Salesforce to Canvas inbound sync webhook.

    The single subclass declares the route. All of the verify, parse, derive,
    dedup, and capture work runs here so the route handler stays one line.

    Fail closed. A missing HMAC secret, a missing signature, or a signature
    mismatch all return 401. A verified event has its action derived from the
    body intent and the record's link state, then is captured as one
    IncomingPatientRecord row and immediately ack'd with 202 Accepted. Capture is
    idempotent. A re sent body identical to the newest row for the same record
    and derived action is dropped rather than duplicated.
    """

    def authenticate(self, credentials: _HMACCredentials) -> bool:
        # The Canvas SimpleAPI authenticate event does not include the request
        # body, so HMAC body verification cannot run here. Real signature
        # verification happens inside the route via _verify_request where
        # self.request.body is populated. We still gate on the secret being
        # configured so a misconfigured plugin fails closed before reaching
        # the route.
        secret = (self.secrets.get("SF_WEBHOOK_SECRET") or "").strip()
        if not secret:
            log.warning("SF_WEBHOOK_SECRET is not configured; denying webhook")
            return False
        return True

    def _verify_request(self) -> Effect | None:
        """Run HMAC verify on the raw body. Returns 401 effect on failure or None on success."""
        secret = (self.secrets.get("SF_WEBHOOK_SECRET") or "").strip()
        signature = self.request.headers.get(SIGNATURE_HEADER)
        if not verify_signature(secret, self.request.body, signature):
            log.warning("Salesforce webhook rejected: invalid HMAC signature")
            return JSONResponse(
                content={"error": "Provided credentials are invalid"},
                status_code=HTTPStatus.UNAUTHORIZED,
            ).apply()
        return None

    def _parse_payload(
        self,
    ) -> tuple[str | None, dict[str, Any] | None, Effect | None]:
        """Load and shape-validate the nested JSON body.

        The body carries a top level ``intent`` and a ``record`` object. Returns
        ``(intent, record, error)`` where the record is the flat Salesforce field
        map captured as ``raw_payload``, the same shape the resolution layer
        already maps through the field mapping.
        """
        try:
            payload = self.request.json()
        except ValueError as exc:
            log.info("Salesforce webhook received invalid JSON: %s", exc)
            return None, None, _bad_request("Invalid JSON payload")

        if not isinstance(payload, dict):
            return None, None, _bad_request("Payload must be a JSON object")

        intent = payload.get("intent")
        if intent not in _VALID_INTENTS:
            return None, None, _bad_request(
                "Missing or invalid 'intent', expected 'sync' or 'delete'"
            )

        record = payload.get("record")
        if not isinstance(record, dict):
            return None, None, _bad_request("Missing or invalid 'record' object")

        if _extract_record_id(record) is None:
            return None, None, _bad_request("Missing required field 'record.Id'")

        return intent, record, None

    def _capture(
        self,
        *,
        record: dict[str, Any],
        sf_record_id: str,
        action: str,
        config: PluginConfig,
    ) -> tuple[IncomingPatientRecord | None, str]:
        """Dedup against the newest row for this record and action, then write one row.

        Returns ``(row, entry_id)``. The row is the freshly captured
        :class:`IncomingPatientRecord` when a new event lands, or ``None`` when an
        identical payload was dropped as a duplicate so the caller knows to skip
        evaluation. The entry_id is the canonical content hash either way. The
        ``record`` is the flat Salesforce field map, stored verbatim as
        ``raw_payload`` so the resolution layer maps it the same way it always
        has.
        """
        content_hash = compute_entry_id(sf_record_id, record)

        newest = (
            IncomingPatientRecord.objects.filter(external_id=sf_record_id, action=action)
            .order_by("-received_at")
            .first()
        )
        if newest is not None and newest.content_hash == content_hash:
            log.info(
                "Salesforce webhook duplicate dropped record=%s action=%s",
                sf_record_id,
                action,
            )
            return None, content_hash

        typed = _map_typed_fields(record, config.field_mapping)
        row = IncomingPatientRecord.objects.create(
            external_id=sf_record_id,
            source_object=config.source_sobject,
            action=action,
            content_hash=content_hash,
            raw_payload=record,
            status="new",
            **typed,
        )

        log.info(
            "Salesforce webhook captured record=%s action=%s sobject=%s",
            sf_record_id,
            action,
            config.source_sobject,
        )
        return row, content_hash

    def _derive_action(self, intent: str, sf_record_id: str) -> str:
        """Resolve a body intent and the record's link state to a stored action.

        A ``delete`` intent maps straight to the delete action. A ``sync`` intent
        is a modify when the Salesforce Id is already linked to a Canvas patient
        and a create when it is not. The caller never names create or modify
        because only the plugin knows the link state. The unlinked but
        demographics match case is left to the resolution UI, where the duplicate
        check already surfaces it.
        """
        if intent == INTENT_DELETE:
            return ACTION_DELETE
        if find_linked_patient_id(sf_record_id) is not None:
            return ACTION_MODIFY
        return ACTION_CREATE

    def _handle_sync(self) -> list[Effect]:
        """Run the full deliberate sync pipeline and return the response effects.

        Verifies the HMAC signature, loads the plugin config, parses the nested
        body, reads the intent, pulls the Id from the record, derives the action
        from the intent and the link state, and captures one
        :class:`IncomingPatientRecord` row. For a fresh event the auto apply
        evaluator then decides whether the row applies automatically or holds for
        a human, for the create and modify verbs of the Sync event and for the
        Delete event alike. A hold writes the reasons onto the row, an auto apply
        builds the Canvas effect, or for a delete dispatches the configured delete
        action, and resolves the row under the automation actor. The response is
        always a 202 Accepted ack carrying the canonical ``entry_id``, with any
        apply effect appended so the runtime lands it. A deduped resend returns the
        202 unchanged.
        """
        if (error := self._verify_request()) is not None:
            return [error]

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            log.warning("Salesforce webhook rejected: %s", exc)
            return [
                JSONResponse(
                    content={"error": str(exc)},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                ).apply()
            ]

        intent, record, parse_error = self._parse_payload()
        if parse_error is not None:
            return [parse_error]
        # _parse_payload guarantees intent and record when error is None.
        assert intent is not None
        assert record is not None

        sf_record_id = _extract_record_id(record)
        assert sf_record_id is not None  # _parse_payload validates record.Id presence

        action = self._derive_action(intent, sf_record_id)

        row, entry_id = self._capture(
            record=record,
            sf_record_id=sf_record_id,
            action=action,
            config=config,
        )

        # A deduped resend (row is None) skips the evaluator. Every freshly
        # captured event runs through it, the create and modify verbs of the Sync
        # event and the Delete event, so the configured filter decides each one.
        apply_effects: list[Effect] = []
        if row is not None:
            apply_effects = self._evaluate_and_apply(
                row=row,
                record=record,
                action=action,
                sf_record_id=sf_record_id,
                config=config,
            )

        return [
            JSONResponse(
                content={"status": "accepted", "entry_id": entry_id},
                status_code=HTTPStatus.ACCEPTED,
            ).apply(),
            *apply_effects,
        ]

    def _evaluate_and_apply(
        self,
        *,
        row: IncomingPatientRecord,
        record: dict[str, Any],
        action: str,
        sf_record_id: str,
        config: PluginConfig,
    ) -> list[Effect]:
        """Run the auto apply evaluator for a fresh Sync row and act on it.

        Returns the apply effects to append to the 202, empty on a hold. On a
        hold the reasons are written onto the row so the Records details can show
        why. On an auto apply the create or modify effect is built and the row is
        resolved under the automation actor, so the Activity ledger shows
        Automatic sync as who acted.
        """
        try:
            mapped = map_record(record, config.field_mapping)
            mapping_failed = False
        except MappingError:
            mapped = MappedPatient(canvas_fields={}, metadata={}, telecom={})
            mapping_failed = True

        facts = self._gather_facts(
            action=action,
            mapped=mapped,
            sf_record_id=sf_record_id,
            mapping_failed=mapping_failed,
        )
        settings = load_sync_settings()
        today = datetime.now(timezone.utc).date()
        decision = evaluate(
            action=action,
            mapped=mapped,
            settings=settings,
            facts=facts,
            today=today,
        )

        if decision.held:
            # A delete with no linked patient has nothing in Canvas to act on, so
            # it stays Activity only exactly as before deletes ran through the
            # evaluator. Skip the hold-reason write so it never surfaces as an
            # actionable Records row, the arrival still lives in the Activity feed.
            if action == ACTION_DELETE and not facts.linked:
                log.info(
                    "Salesforce sync delete has no linked patient, activity only "
                    "record=%s",
                    sf_record_id,
                )
                return []
            IncomingPatientRecord.objects.filter(pk=row.pk).update(
                hold_reasons=list(decision.reasons)
            )
            log.info(
                "Salesforce sync held record=%s action=%s reasons=%s",
                sf_record_id,
                action,
                list(decision.reasons),
            )
            return []

        if action == ACTION_CREATE:
            return self._auto_apply_create(
                row=row, mapped=mapped, sf_record_id=sf_record_id, settings=settings
            )
        if action == ACTION_MODIFY:
            return self._auto_apply_modify(
                row=row, mapped=mapped, sf_record_id=sf_record_id, settings=settings
            )
        return self._auto_apply_delete(
            row=row, sf_record_id=sf_record_id, settings=settings
        )

    def _gather_facts(
        self,
        *,
        action: str,
        mapped: MappedPatient,
        sf_record_id: str,
        mapping_failed: bool,
    ) -> SyncFacts:
        """Collect the history the evaluator's hard gates read.

        The link state, whether a create for this id was already accepted but its
        asynchronous link has not landed yet, whether the newest decision for the
        contact was a skip, and for an unlinked create whether the incoming
        demographics match an existing patient. The duplicate and link pending
        gates only apply to the create verb, so the queries that back them only
        run for a create.
        """
        linked = find_linked_patient_id(sf_record_id) is not None

        accepted_create_exists = False
        duplicate_match = False
        if action == ACTION_CREATE:
            accepted_create_exists = IncomingPatientRecord.objects.filter(
                external_id=sf_record_id,
                action=ACTION_CREATE,
                status=_STATUS_ACCEPTED,
            ).exists()
            duplicate_match = self._has_duplicate(mapped)

        return SyncFacts(
            linked=linked,
            accepted_create_exists=accepted_create_exists,
            previously_skipped=self._most_recent_decision_was_skip(sf_record_id),
            duplicate_match=duplicate_match,
            mapping_failed=mapping_failed,
        )

    def _has_duplicate(self, mapped: MappedPatient) -> bool:
        """True when an unlinked create matches an existing patient.

        Reuses the shared last name plus birth date lookup the duplicate check
        route serves, so a gated duplicate and a surfaced duplicate can never
        drift. A missing last name or an unparseable birth date does not fire the
        gate, the required and validity layers cover those.
        """
        fields = mapped.canvas_fields
        last_name = str(fields.get("last_name") or "").strip()
        birth_date = _coerce_birthdate(fields.get("date_of_birth"))
        if not last_name or birth_date is None:
            return False
        return bool(
            find_duplicate_patients(last_name=last_name, birth_date=birth_date, limit=1)
        )

    def _most_recent_decision_was_skip(self, sf_record_id: str) -> bool:
        """True when the newest resolution for the contact was a skip.

        The skipped gate stands in for an explicit never sync flag. A later
        reopen writes its own decision, so the newest decision is no longer a
        skip and the gate releases.
        """
        latest = (
            ResolutionAuditEntry.objects.filter(external_id=sf_record_id)
            .order_by("-created_at", "-dbid")
            .values_list("action_taken", flat=True)
            .first()
        )
        return bool(latest == _ACTION_TAKEN_SKIPPED)

    def _auto_apply_create(
        self,
        *,
        row: IncomingPatientRecord,
        mapped: MappedPatient,
        sf_record_id: str,
        settings: SyncSettings,
    ) -> list[Effect]:
        """Build the create effect and resolve the row under the automation actor."""
        effect = build_create_patient_effect(mapped=mapped, sf_record_id=sf_record_id)
        write_resolution(
            row,
            status=_STATUS_ACCEPTED,
            action_taken=_ACTION_TAKEN_CREATED,
            actor=AUTOMATIC_ACTOR,
            now=datetime.now(timezone.utc),
            extra_fields={
                "first_name": str(mapped.canvas_fields.get("first_name") or ""),
                "last_name": str(mapped.canvas_fields.get("last_name") or ""),
                "email": str(mapped.canvas_fields.get("email") or ""),
                "phone": str(mapped.canvas_fields.get("phone") or ""),
            },
            note=_auto_apply_note(ACTION_CREATE, settings),
        )
        log.info("Salesforce sync auto applied create record=%s", sf_record_id)
        return [effect]

    def _auto_apply_modify(
        self,
        *,
        row: IncomingPatientRecord,
        mapped: MappedPatient,
        sf_record_id: str,
        settings: SyncSettings,
    ) -> list[Effect]:
        """Build the update effect, snapshot the chart, and resolve the row.

        Snapshots the linked patient before the update lands so the Activity
        Details table can show what was in Canvas against what the apply wrote,
        exactly as the manual modify apply does. If the link cannot be resolved
        at apply time the row holds rather than dropping, the response stays 202.
        """
        canvas_patient_id = find_linked_patient_id(sf_record_id)
        if canvas_patient_id is None:
            IncomingPatientRecord.objects.filter(pk=row.pk).update(
                hold_reasons=[_REASON_MODIFY_LINK_LOST]
            )
            log.warning(
                "Salesforce sync modify held, link lost record=%s", sf_record_id
            )
            return []

        canvas_before = canvas_demographics_by_id(canvas_patient_id)
        effect = build_update_patient_effect(
            canvas_patient_id=canvas_patient_id, mapped=mapped
        )

        # Mirror the typed columns the manual modify apply writes, only the keys
        # the payload actually carries, so absent keys leave the captured columns
        # alone and the delta apply contract holds.
        extra_fields: dict[str, Any] = {}
        for column in ("first_name", "last_name", "email", "phone"):
            if column in mapped.canvas_fields:
                extra_fields[column] = str(mapped.canvas_fields[column])

        write_resolution(
            row,
            status=_STATUS_ACCEPTED,
            action_taken=_ACTION_TAKEN_MODIFY_APPLIED,
            actor=AUTOMATIC_ACTOR,
            now=datetime.now(timezone.utc),
            extra_fields=extra_fields,
            result_patient_id=canvas_patient_id,
            canvas_before=canvas_before,
            note=_auto_apply_note(ACTION_MODIFY, settings),
        )
        log.info(
            "Salesforce sync auto applied modify record=%s patient=%s",
            sf_record_id,
            canvas_patient_id,
        )
        return [effect]

    def _auto_apply_delete(
        self,
        *,
        row: IncomingPatientRecord,
        sf_record_id: str,
        settings: SyncSettings,
    ) -> list[Effect]:
        """Dispatch the configured delete action for an auto applied delete.

        A delete with no linked Canvas patient has nothing to delete, so it stays
        Activity only exactly as before, the row is captured and nothing else
        happens. Tag deleted is effect based with no external dependency. Mark
        inactive and unlink call the Canvas FHIR client synchronously, and any
        configuration or transport failure degrades the delete to a manual hold
        rather than failing the webhook, which always answers 202.
        """
        canvas_patient_id = find_linked_patient_id(sf_record_id)
        if canvas_patient_id is None:
            log.info(
                "Salesforce sync delete has no linked patient, activity only "
                "record=%s",
                sf_record_id,
            )
            return []

        if settings.delete_action == DELETE_ACTION_TAG_DELETED:
            return self._auto_apply_tag_deleted(
                row=row,
                sf_record_id=sf_record_id,
                canvas_patient_id=canvas_patient_id,
            )
        return self._auto_apply_fhir_delete(
            row=row,
            sf_record_id=sf_record_id,
            canvas_patient_id=canvas_patient_id,
            delete_action=settings.delete_action,
        )

    def _auto_apply_tag_deleted(
        self,
        *,
        row: IncomingPatientRecord,
        sf_record_id: str,
        canvas_patient_id: str,
    ) -> list[Effect]:
        """Tag the linked patient as Salesforce deleted, effect based.

        Mirrors the manual tag deleted route, the same metadata effect carrying
        the delete event time and the same action_taken vocabulary, only the
        actor differs.
        """
        effect = build_tag_deleted_effect(
            canvas_patient_id=canvas_patient_id,
            deleted_at=row.received_at,
        )
        write_resolution(
            row,
            status=_STATUS_ACCEPTED,
            action_taken=_ACTION_TAKEN_TAG_DELETED,
            actor=AUTOMATIC_ACTOR,
            now=datetime.now(timezone.utc),
            result_patient_id=canvas_patient_id,
            note=_auto_apply_delete_note(DELETE_ACTION_TAG_DELETED),
        )
        log.info(
            "Salesforce sync auto applied tag deleted record=%s patient=%s",
            sf_record_id,
            canvas_patient_id,
        )
        return [effect]

    def _auto_apply_fhir_delete(
        self,
        *,
        row: IncomingPatientRecord,
        sf_record_id: str,
        canvas_patient_id: str,
        delete_action: str,
    ) -> list[Effect]:
        """Mark inactive or unlink the linked patient through the Canvas FHIR client.

        Both call the FHIR client synchronously inside the webhook, guarded by the
        same configuration predicate the manual routes use. A ConfigError, a
        missing FHIR configuration, or an auth or transport failure degrades the
        delete to a manual hold naming the failure, the webhook never returns an
        error for a degradation. Reuses the FHIR client and the same action_taken
        vocabulary the manual mark inactive and unlink routes write.
        """
        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            return self._degrade_delete(
                row, sf_record_id, _REASON_FHIR_NOT_CONFIGURED, exc
            )
        if not canvas_fhir_configured(config):
            return self._degrade_delete(
                row, sf_record_id, _REASON_FHIR_NOT_CONFIGURED, None
            )

        try:
            client = self._build_canvas_fhir_client(config)
            if delete_action == DELETE_ACTION_MARK_INACTIVE:
                client.mark_patient_inactive(canvas_patient_id)
                action_taken = _ACTION_TAKEN_MARK_INACTIVE
            else:
                client.remove_salesforce_identifier(canvas_patient_id, sf_record_id)
                action_taken = _ACTION_TAKEN_UNLINK
        except (
            CanvasFhirNotConfiguredError,
            CanvasFhirAuthError,
            CanvasFhirError,
        ) as exc:
            return self._degrade_delete(
                row, sf_record_id, _REASON_FHIR_DELETE_FAILED, exc
            )

        write_resolution(
            row,
            status=_STATUS_ACCEPTED,
            action_taken=action_taken,
            actor=AUTOMATIC_ACTOR,
            now=datetime.now(timezone.utc),
            result_patient_id=canvas_patient_id,
            note=_auto_apply_delete_note(delete_action),
        )
        log.info(
            "Salesforce sync auto applied %s record=%s patient=%s",
            action_taken,
            sf_record_id,
            canvas_patient_id,
        )
        return []

    def _degrade_delete(
        self,
        row: IncomingPatientRecord,
        sf_record_id: str,
        reason: str,
        exc: Exception | None,
    ) -> list[Effect]:
        """Hold an auto applied delete that could not reach Canvas FHIR.

        Writes the reason onto the row so the held delete surfaces in the Records
        list for a human, leaves the status at new, and returns no effect. The
        webhook still answers 202, a degradation is never an error to Salesforce.
        """
        IncomingPatientRecord.objects.filter(pk=row.pk).update(hold_reasons=[reason])
        log.warning(
            "Salesforce sync delete degraded to hold record=%s reason=%s err=%s",
            sf_record_id,
            reason,
            exc,
        )
        return []

    def _build_canvas_fhir_client(self, config: PluginConfig) -> CanvasFhirClient:
        """Construct the Canvas FHIR client for the auto applied delete actions.

        Mirrors the status API seam so tests can swap a fake client without monkey
        patching the SDK ``Http`` import. The optional token host override is
        threaded from secrets exactly as the manual routes thread it.
        """
        return build_canvas_fhir_client(
            http=Http(),
            fumage_base_url=config.fumage_base_url,
            client_id=config.canvas_api_client_id,
            client_secret=config.canvas_api_client_secret,
            instance_url=config.canvas_instance_url,
        )


def _auto_apply_delete_note(delete_action: str) -> str:
    """A short stable note naming the delete action an auto applied delete took.

    Stored on the decision entry and rendered in the Activity Details so an
    operator can see the delete applied itself and which mechanism it used.
    """
    label = {
        DELETE_ACTION_TAG_DELETED: "tag deleted",
        DELETE_ACTION_MARK_INACTIVE: "mark inactive",
        DELETE_ACTION_UNLINK: "unlink",
    }.get(delete_action, delete_action)
    return f"Automatically applied delete ({label})."


def _auto_apply_note(action: str, settings: SyncSettings) -> str:
    """A short stable note naming the filters an auto applied row passed.

    Stored on the decision entry and rendered in the Activity Details, so an
    operator can see the sync applied itself and which enabled checks it cleared.
    """
    passed = ["required fields"]
    if settings.address_group_integrity:
        passed.append("address integrity")
    if settings.validity_checks:
        passed.append("validity")
    verb = "create" if action == ACTION_CREATE else "modify"
    return f"Automatically applied {verb}. Passed enabled filters: {', '.join(passed)}."


__all__ = (
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_MODIFY",
    "INTENT_DELETE",
    "INTENT_SYNC",
    "SalesforceWebhookBase",
    "_HMACCredentials",
    "_extract_record_id",
    "_map_typed_fields",
)
