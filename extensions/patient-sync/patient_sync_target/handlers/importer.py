"""Target-side handler: receives a patient bundle and dispatches import effects.

Authenticates incoming requests via APIKeyAuthMixin against the
``simpleapi-api-key`` secret. The paired source plugin holds the same
value and presents it as ``Authorization: <key>``.

For the *currently possible* release, the dispatcher knows how to write
Patient, Note, Command, and Task records (Patient with a new key per
Canvas's globally-unique-key invariant; the others with preserved ids).
Every other entity type in the bundle is reported in the response's
``unsupported_entities`` list until its plumbing fix or new-effect work
lands (see SPEC.md).
"""

from __future__ import annotations

import json
from typing import Any

from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from patient_sync_target.models.applied_sync import AppliedSync
from patient_sync_target.services.dispatcher import (
    SUPPORTED_ENTITY_TYPES,
    AlreadyApplied,
    UnknownCommandSchemaKey,
    UnsupportedEntityType,
    dispatch,
)


# Strict dependency order: Patient before Note, Note before Command.
APPLY_ORDER: tuple[str, ...] = ("Patient", "Note", "Command", "Task")

# Mirror of bundle_walker.PROVISION_SYSTEM — the `system` value used on the
# marker external_identifier that source attaches to provisioned Patients.
# Caller polls /provisioned/<token>; we look up the patient by that marker.
PROVISION_SYSTEM = "patient-sync:provision-token"


class PatientSyncTargetAPI(APIKeyAuthMixin, SimpleAPI):
    """Receives patient bundles from a paired source plugin. See SPEC.md."""

    PREFIX = ""

    @api.post("/sync")
    def receive_sync(self) -> list[Response | Effect]:
        raw_body = self.request.body or b""

        try:
            bundle = json.loads(raw_body)
        except json.JSONDecodeError:
            return [JSONResponse({"error": "invalid json"}, status_code=400)]

        sync_id = bundle.get("sync_id")
        if not sync_id:
            return [JSONResponse({"error": "sync_id is required"}, status_code=400)]

        if self._already_applied(sync_id):
            return [JSONResponse({"sync_id": sync_id, "status": "succeeded"}, status_code=200)]

        validation_errors = self._validate_bundle(bundle)
        if validation_errors:
            return [
                JSONResponse(
                    {"sync_id": sync_id, "status": "rejected", "errors": validation_errors},
                    status_code=400,
                )
            ]

        effects, dispatched, skipped, unsupported, errors = self._dispatch_bundle(bundle)
        self._record_applied(sync_id)

        log.info(
            f"patient_sync_target sync_id={sync_id} dispatched={dispatched} "
            f"skipped={skipped} unsupported={unsupported} errors={errors}"
        )

        return [
            *effects,
            JSONResponse(
                {
                    "sync_id": sync_id,
                    "status": "dispatched",
                    "dispatched": dispatched,
                    "skipped_already_present": skipped,
                    "unsupported_entities": unsupported,
                    "errors": errors,
                },
                status_code=202,
            ),
        ]

    def _validate_bundle(self, bundle: dict[str, Any]) -> list[dict[str, str]]:
        """Two-call protocol: provision bundle has exactly Patient and nothing
        else; remap bundle has Notes/Commands/Tasks and no Patient. So no
        per-entity requirement, just the schema-version sanity check."""
        errors: list[dict[str, str]] = []
        if bundle.get("schema_version") != "1.0":
            errors.append({"entity": "_bundle", "reason": "unsupported schema_version"})
        return errors

    def _dispatch_bundle(
        self,
        bundle: dict[str, Any],
    ) -> tuple[
        list[Effect],
        dict[str, int],
        dict[str, int],
        dict[str, int],
        list[dict[str, str]],
    ]:
        """Walk the bundle in dependency order and turn each record into an effect.

        Returns the effects to fire, counts per dispatched entity type,
        counts per skipped (already-present) entity type, counts per
        unsupported entity type, and per-record errors.
        """
        effects: list[Effect] = []
        dispatched: dict[str, int] = {}
        skipped: dict[str, int] = {}
        unsupported: dict[str, int] = {}
        errors: list[dict[str, str]] = []
        entities = bundle.get("entities") or {}

        # Anything in the bundle that isn't in APPLY_ORDER goes straight to
        # ``unsupported_entities`` — even if SUPPORTED_ENTITY_TYPES would
        # accept it, the apply order is the contract.
        for entity_type, records in entities.items():
            if entity_type not in APPLY_ORDER and records:
                unsupported[entity_type] = len(records)

        for entity_type in APPLY_ORDER:
            if entity_type not in SUPPORTED_ENTITY_TYPES:
                records = entities.get(entity_type) or []
                if records:
                    unsupported[entity_type] = len(records)
                continue
            records = entities.get(entity_type) or []
            for record in records:
                try:
                    effects.append(dispatch(entity_type, record))
                    dispatched[entity_type] = dispatched.get(entity_type, 0) + 1
                except AlreadyApplied:
                    skipped[entity_type] = skipped.get(entity_type, 0) + 1
                except UnknownCommandSchemaKey as exc:
                    errors.append({
                        "entity": entity_type,
                        "id": record.get("id", "?"),
                        "reason": f"unknown command schema_key: {exc}",
                    })
                except UnsupportedEntityType as exc:
                    errors.append({
                        "entity": entity_type,
                        "id": record.get("id", "?"),
                        "reason": f"unsupported entity type: {exc}",
                    })
                except Exception as exc:
                    errors.append({
                        "entity": entity_type,
                        "id": record.get("id", "?"),
                        "reason": f"{exc.__class__.__name__}: {exc}",
                    })

        return effects, dispatched, skipped, unsupported, errors

    @api.get("/provisioned/<provision_token>")
    def lookup_provisioned(self) -> list[Response | Effect]:
        """Step 2 of the two-call protocol's caller-side polling.

        Source calls ``POST /sync`` with a Patient that carries a
        provision_token marker external_identifier. The async
        Patient.create() lands the patient on plugin-testing with a new
        server-assigned key. The caller polls this endpoint with the same
        token; once Canvas finishes the create, the eid row exists and
        we return ``{target_patient_id: <new key>}``.

        Returns 404 until the patient is found — caller's expected behavior
        is a simple retry loop with a backoff.
        """
        provision_token = self.request.path_params["provision_token"]
        eid = (
            PatientExternalIdentifier.objects
            .filter(system=PROVISION_SYSTEM, value=provision_token)
            .select_related("patient")
            .order_by("-dbid")
            .first()
        )
        if not eid:
            return [JSONResponse({"error": "not yet provisioned"}, status_code=404)]
        return [
            JSONResponse(
                {"provision_token": provision_token, "target_patient_id": eid.patient.id},
                status_code=200,
            )
        ]

    def _already_applied(self, sync_id: str) -> bool:
        """Replay-prevention lookup against the plugin's namespace store."""
        return AppliedSync.objects.filter(sync_id=sync_id).exists()

    def _record_applied(self, sync_id: str) -> None:
        """Persist that this sync_id has been dispatched. Retention is forever (no auto-prune)."""
        AppliedSync.objects.get_or_create(sync_id=sync_id)
