"""Source-side handler: walks a patient graph, anonymizes PHI, POSTs to target.

Two-call protocol (see SPEC.md):

1. ``POST /export/provision-patient`` — walks just Patient + a
   ``provision_token`` marker, dispatches Patient.create() on target.
   Returns the token + a target URL the caller polls.
2. ``POST /export`` with ``target_patient_id`` — walks the full bundle,
   rewrites every Note/Command/Task patient_id reference to the
   target-side key, dispatches.

Both endpoints are API-key authenticated. The same-instance guard refuses
any ``target_url`` whose host matches this plugin's ``source_host``.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any
from uuid import uuid4

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.http_request import HttpRequestEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from patient_sync_source.services.anonymizer import Anonymizer
from patient_sync_source.services.bundle_walker import BundleWalker


class PatientSyncSourceAPI(APIKeyAuthMixin, SimpleAPI):
    """Cross-instance patient export. See SPEC.md."""

    PREFIX = ""

    @api.post("/export/provision-patient")
    def provision_patient(self) -> list[Response | Effect]:
        """Step 1 of two-call protocol — provision a patient on target.

        Walks just the Patient record, attaches a ``provision_token`` marker
        as an external_identifier, dispatches Patient.create() on target.
        Caller polls ``target_provisioned_url`` until it returns 200 with
        the new ``target_patient_id``, then posts to ``/export`` with that
        id as ``target_patient_id``.
        """
        validation = self._validate_request(self.request.json())
        if isinstance(validation, JSONResponse):
            return [validation]
        patient, target_url, _callback_url, body = validation

        sync_id = str(uuid4())
        provision_token = str(uuid4())
        anonymizer = self._anonymizer_for(patient)
        walker = self._walker_for(patient, anonymizer=anonymizer, sync_id=sync_id)
        bundle = walker.build_provision(provision_token=provision_token)

        return [
            self._dispatch_to_target(bundle, target_url=target_url, sync_id=sync_id),
            JSONResponse(
                {
                    "sync_id": sync_id,
                    "provision_token": provision_token,
                    "target_provisioned_url": _make_provisioned_url(target_url, provision_token),
                    "patient_id": patient.id,
                    "status": "accepted",
                },
                status_code=202,
            ),
        ]

    @api.post("/export")
    def export_patient(self) -> list[Response | Effect]:
        """Step 2 — sync everything except the Patient, FKs rewritten.

        Requires ``target_patient_id`` in the request body. The caller gets
        this from the provision-step response after polling the target's
        ``GET /provisioned/<token>`` endpoint.
        """
        body = self.request.json()
        validation = self._validate_request(body)
        if isinstance(validation, JSONResponse):
            return [validation]
        patient, target_url, callback_url, body = validation

        target_patient_id = body.get("target_patient_id")
        if not target_patient_id:
            return [
                JSONResponse(
                    {
                        "error": (
                            "target_patient_id is required. Call POST "
                            "/export/provision-patient first, then poll "
                            "target's GET /provisioned/<token> for the new key."
                        )
                    },
                    status_code=400,
                )
            ]

        sync_id = str(uuid4())
        anonymizer = self._anonymizer_for(patient)
        walker = self._walker_for(patient, anonymizer=anonymizer, sync_id=sync_id)
        bundle = walker.build_remap(target_patient_id=target_patient_id)

        effects: list[Response | Effect] = [
            self._dispatch_to_target(bundle, target_url=target_url, sync_id=sync_id),
        ]
        if callback_url:
            effects.append(self._schedule_callback(callback_url, sync_id=sync_id))
        effects.append(
            JSONResponse(
                {
                    "sync_id": sync_id,
                    "status": "accepted",
                    "patient_id": patient.id,
                    "target_patient_id": target_patient_id,
                },
                status_code=202,
            )
        )
        return effects

    # ---------- Shared validation / resolution ----------

    def _validate_request(
        self,
        body: dict[str, Any],
    ) -> JSONResponse | tuple[Patient, str, str | None, dict[str, Any]]:
        """Common validation for both endpoints. Returns either a JSONResponse on error
        or the tuple (patient, target_url, callback_url, body) on success."""
        patient_id = body.get("patient_id")
        external_identifier = body.get("external_identifier")
        target_url = body.get("target_url")
        callback_url = body.get("callback_url")

        if not target_url:
            return JSONResponse({"error": "target_url is required"}, status_code=400)
        if not (patient_id or external_identifier):
            return JSONResponse(
                {"error": "patient_id or external_identifier is required"},
                status_code=400,
            )
        if self._is_same_instance(target_url):
            return JSONResponse(
                {"error": "same-instance refused: target_url resolves to this instance"},
                status_code=400,
            )

        patient = self._resolve_patient(patient_id, external_identifier)
        if patient is None:
            return JSONResponse({"error": "patient not found"}, status_code=404)

        return patient, target_url, callback_url, body

    def _resolve_patient(
        self,
        patient_id: str | None,
        external_identifier: Any,
    ) -> Patient | None:
        if patient_id:
            return Patient.objects.filter(id=patient_id).first()
        # external_identifier shape: {"system": "...", "value": "..."} or just a string
        # to match the value with any system.
        if isinstance(external_identifier, dict):
            qs = PatientExternalIdentifier.objects.filter(value=external_identifier.get("value", ""))
            if system := external_identifier.get("system"):
                qs = qs.filter(system=system)
        else:
            qs = PatientExternalIdentifier.objects.filter(value=external_identifier)
        eid = qs.select_related("patient").order_by("-dbid").first()
        return eid.patient if eid else None

    # ---------- Bundle build ----------

    def _anonymizer_for(self, patient: Patient) -> Anonymizer:
        return Anonymizer(
            anonymization_key=self.secrets["anonymization_key"],
            source_patient_id=patient.id,
        )

    def _walker_for(
        self,
        patient: Patient,
        *,
        anonymizer: Anonymizer,
        sync_id: str,
    ) -> BundleWalker:
        return BundleWalker(
            patient=patient,
            anonymizer=anonymizer,
            source_instance=self.secrets.get("source_host", ""),
            sync_id=sync_id,
            exported_at=arrow.utcnow().isoformat(),
        )

    # ---------- Outbound ----------

    def _dispatch_to_target(
        self,
        bundle: dict[str, Any],
        *,
        target_url: str,
        sync_id: str,
    ) -> Effect:
        body = json.dumps(bundle)
        return HttpRequestEffect(
            url=target_url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": self.secrets["target_api_key"],
                "X-Canvas-Sync-Id": sync_id,
            },
            body=body,
            retry_on_status_codes=[500, 502, 503, 504],
        ).apply().set_async(max_retries=3)

    def _schedule_callback(self, callback_url: str, *, sync_id: str) -> Effect:
        """Fire the caller callback after target dispatch.

        Today this fires immediately on dispatch with status="dispatched"
        because the plugin runtime doesn't expose "effects settled" signals
        (SPEC.md > SDK gaps). When that primitive lands, this method will
        wait for the target's per-entity outcomes before reporting.
        """
        body = json.dumps({"sync_id": sync_id, "status": "dispatched"})
        signature = _sign(body, self.secrets["callback_shared_secret"])
        return HttpRequestEffect(
            url=callback_url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Canvas-Sync-Id": sync_id,
                "X-Canvas-Signature": f"sha256={signature}",
            },
            body=body,
        ).apply().set_async(max_retries=5)

    # ---------- Guards ----------

    def _is_same_instance(self, target_url: str) -> bool:
        """Refuse syncs that point back at the source's own host."""
        target_host = _hostname_from_url(target_url)
        if not target_host:
            return False
        source_host = self.secrets.get("source_host", "").strip().lower()
        return bool(source_host) and target_host == source_host


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode(), body.encode(), sha256).hexdigest()


def _hostname_from_url(url: str) -> str:
    """Extract the lowercased hostname from a URL.

    Hand-rolled because `urllib.parse.urlparse` isn't on the Canvas plugin
    sandbox's allowed-imports list.
    """
    if "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    for sep in ("/", "?", "#"):
        idx = rest.find(sep)
        if idx >= 0:
            rest = rest[:idx]
    if ":" in rest:  # strip port
        rest = rest.split(":", 1)[0]
    return rest.lower()


def _make_provisioned_url(target_url: str, provision_token: str) -> str:
    """Turn the target's `/sync` URL into its `/provisioned/<token>` URL.

    Assumes the target plugin's two routes share a prefix and only differ
    in the trailing path segment.
    """
    if target_url.endswith("/sync"):
        return target_url[: -len("/sync")] + f"/provisioned/{provision_token}"
    return target_url.rstrip("/") + f"/provisioned/{provision_token}"
