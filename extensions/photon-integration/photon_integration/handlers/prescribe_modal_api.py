"""SimpleAPI serving the Photon Elements prescribe modal.

Routes (under /plugin-io/api/photon_integration/photon/):

| GET / | HTML shell embedding Photon Elements, configured for the patient |
| GET /main.js   | client JS that mounts photon-client + photon-prescribe-workflow |
| GET /styles.css| modal styles |

The shell resolves the patient's Photon id server-side (creating + persisting it
via the M2M client when absent), then hands off to the browser where the
provider authenticates (user token with write:prescription) and prescribes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.patient import Patient
from logger import log

from photon_integration.client.photon_client import PhotonClient, PhotonError
from photon_integration.command_payload import extract_rx
from photon_integration.constants import PHOTON_COMMAND_SCHEMA_KEYS
from photon_integration.handlers.command_field import _photon_send_selected
from photon_integration.ontology import fdb_to_rxcui, ndc_to_rxcui
from photon_integration.prescriber import resolve_prescriber, staff_identity
from photon_integration.patient_sync import (
    build_address,
    build_client,
    resolve_photon_patient,
)

_GRAPHQL_URLS = {
    "sandbox": "https://api.neutron.health/graphql",
    "production": "https://api.photon.health/graphql",
}


def _safe_json(obj: Any) -> str:
    """Serialize ``obj`` for safe embedding in an inline ``<script>`` block.

    ``json.dumps`` does not escape ``</script>`` or the U+2028/U+2029 line
    separators, so values sourced from patient/staff data (e.g. the patient
    address) could break out of the script tag and execute. Escaping ``<``/``>``/
    ``&`` and the two line separators neutralizes that without affecting
    ``JSON.parse`` (they are valid JSON unicode escapes).
    """
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _photon_med_label(med: dict[str, Any] | None) -> str | None:
    """Human label for the Photon match so the provider can verify it."""
    if not med:
        return None
    name = med.get("name") or ""
    brand = med.get("brandName")
    return f"{brand} — {name}".strip(" —") if brand else (name or None)

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PhotonPrescribeModalAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the Photon Elements prescribe modal shell and assets."""

    PREFIX = "/photon"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        params = self.request.query_params
        patient_id = (params.get("patient_id") or "").strip()
        # After provider SSO, Auth0 redirects back here with code/state and no
        # patient_id; render the shell so photon-client can finish the login (the
        # browser carries the Photon patient id across the redirect).
        is_oauth_callback = bool(params.get("code") and params.get("state"))

        spa_client_id = (self.secrets.get("PHOTON_SPA_CLIENT_ID") or "").strip()
        org_id = (self.secrets.get("PHOTON_ORG_ID") or "").strip()
        if not spa_client_id or not org_id:
            return [
                self._error_page(
                    "Photon Elements is not configured "
                    "(PHOTON_SPA_CLIENT_ID / PHOTON_ORG_ID)."
                )
            ]

        effects: list[Response | Effect] = []
        photon_patient_id = ""
        if patient_id:
            try:
                patient = Patient.objects.get(id=patient_id)
            except Patient.DoesNotExist:
                return [self._error_page("Patient not found.")]
            try:
                photon_patient_id, ext_id_effect = resolve_photon_patient(
                    patient, build_client(self.secrets)
                )
            except PhotonError as exc:
                log.error("Photon patient sync failed for %s: %s", patient_id, exc)
                return [self._error_page(f"Could not sync the patient to Photon: {exc}")]
            if ext_id_effect is not None:
                effects.append(ext_id_effect)
        elif not is_oauth_callback:
            return [self._error_page("No patient was provided to the Photon modal.")]

        env = (self.secrets.get("PHOTON_ENV") or "sandbox").strip().lower()
        operator = staff_identity(self.request.headers.get("canvas-logged-in-user-id"))
        config = {
            "clientId": spa_client_id,
            "org": org_id,
            "patientId": photon_patient_id,
            "devMode": env != "production",
            "redirectUri": self._redirect_uri(),
            "canvasUserEmail": operator["email"],
            "canvasUserName": operator["name"],
        }
        html = render_to_string(
            "static/index.html",
            {"cache_bust": _CACHE_BUST, "config_json": _safe_json(config)},
        )
        effects.append(
            HTMLResponse(html, status_code=HTTPStatus.OK, headers={"Cache-Control": "no-store"})
        )
        return effects

    @api.get("/elements.js")
    def elements_js(self) -> list[Response | Effect]:
        # Photon Elements is vendored (static/elements_bundle.js, wrapped in a
        # Django {% verbatim %} block) and served same-origin so it isn't subject
        # to cross-origin script-src/CSP restrictions inside the Canvas modal.
        return [
            Response(
                render_to_string("static/elements_bundle.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        ]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/send.js")
    def send_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/send.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/send")
    def send(self) -> list[Response | Effect]:
        """API-direct send modal: build the flagged Rx from the note's commands.

        The provider authenticates in the browser (user token) and submits each
        prescription/order directly via the Photon SDK.
        """
        params = self.request.query_params
        note_id = (params.get("note_id") or "").strip()
        is_oauth_callback = bool(params.get("code") and params.get("state"))

        spa_client_id = (self.secrets.get("PHOTON_SPA_CLIENT_ID") or "").strip()
        org_id = (self.secrets.get("PHOTON_ORG_ID") or "").strip()
        if not spa_client_id or not org_id:
            return [self._error_page("Photon is not configured (SPA client id / org).")]

        env = (self.secrets.get("PHOTON_ENV") or "sandbox").strip().lower()
        effects: list[Response | Effect] = []
        photon_patient_id = ""
        address: dict[str, Any] | None = None
        prescriptions: list[dict[str, Any]] = []
        if note_id:
            client = build_client(self.secrets)
            patient, prescriptions = self._gather_flagged_prescriptions(note_id, client)
            if patient is not None:
                try:
                    photon_patient_id, ext_id_effect = resolve_photon_patient(patient, client)
                except PhotonError as exc:
                    log.error("Photon patient sync failed (send) for note %s: %s", note_id, exc)
                    return [self._error_page(f"Could not sync the patient to Photon: {exc}")]
                if ext_id_effect is not None:
                    effects.append(ext_id_effect)
                address = build_address(patient)
                for rx in prescriptions:
                    rx["patientId"] = photon_patient_id
        elif not is_oauth_callback:
            return [self._error_page("No note was provided to the Photon send modal.")]

        # The operator (logged-in Canvas user) must be the signed-in Photon
        # provider, so nobody can send under a cached session for someone else.
        operator = staff_identity(self.request.headers.get("canvas-logged-in-user-id"))
        config = {
            "clientId": spa_client_id,
            "org": org_id,
            "patientId": photon_patient_id,
            "devMode": env != "production",
            "redirectUri": self._redirect_uri("send"),
            "graphqlUrl": _GRAPHQL_URLS["sandbox" if env != "production" else "production"],
            "address": address,
            "canvasUserEmail": operator["email"],
            "canvasUserName": operator["name"],
            "prescriptions": prescriptions,
        }
        html = render_to_string(
            "static/send.html",
            {"cache_bust": _CACHE_BUST, "config_json": _safe_json(config)},
        )
        effects.append(
            HTMLResponse(html, status_code=HTTPStatus.OK, headers={"Cache-Control": "no-store"})
        )
        return effects

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _gather_flagged_prescriptions(
        note_id: str, client: PhotonClient
    ) -> tuple[Patient | None, list[dict[str, Any]]]:
        """Return (patient, prescription payloads) for 'Send via Photon' commands."""
        commands = Command.objects.filter(
            note__dbid=note_id,
            schema_key__in=PHOTON_COMMAND_SCHEMA_KEYS,
            committer__isnull=False,
            entered_in_error__isnull=True,
        )
        patient: Patient | None = None
        prescriptions: list[dict[str, Any]] = []
        for command in commands:
            if not _photon_send_selected(command.id):
                continue
            if patient is None:
                patient = command.patient
            data = command.data or {}
            rx = extract_rx(data)
            term = rx.pop("term")
            fdb = rx.pop("fdbCode")
            ndc = rx.pop("ndc")
            prescriber = resolve_prescriber(data)
            # Exact, code-based match: Canvas FDB code (or NDC) -> RxNorm via the
            # Ontologies service -> Photon drug.code. Never guess by name.
            rxcui = fdb_to_rxcui(fdb) or ndc_to_rxcui(ndc)
            photon_med = client.find_treatment_by_code(rxcui)
            treatment_id = str(photon_med["id"]) if photon_med else None
            if not treatment_id and not rxcui:
                error = "No RxNorm code for this medication — use Prescribe via Photon"
            elif not treatment_id:
                error = f"No Photon match for RxNorm {rxcui} — use Prescribe via Photon"
            elif not rx["dispenseUnit"]:
                # Don't auto-send a wrong unit (e.g. "0.75 mL syringe").
                error = "Dispense unit not supported by Photon — use Prescribe via Photon"
            else:
                error = None
            prescriptions.append(
                {
                    "commandId": str(command.id),
                    "externalId": str(command.id),
                    "treatmentId": treatment_id,
                    "medication": term or "prescription",
                    "photonMedication": _photon_med_label(photon_med),
                    "rxcui": rxcui,
                    "prescriberEmail": prescriber["email"],
                    "prescriberName": prescriber["name"],
                    "error": error,
                    **rx,
                }
            )
        return patient, prescriptions

    def _redirect_uri(self, path: str = "") -> str:
        override = (self.secrets.get("PHOTON_REDIRECT_URI") or "").strip()
        base = override or (
            f"https://{self.request.headers.get('host', '')}"
            "/plugin-io/api/photon_integration/photon/"
        )
        return f"{base.rstrip('/')}/{path}" if path else base

    @staticmethod
    def _error_page(message: str) -> HTMLResponse:
        body = render_to_string("static/error.html", {"message": message})
        return HTMLResponse(body, status_code=HTTPStatus.OK, headers={"Cache-Control": "no-store"})
