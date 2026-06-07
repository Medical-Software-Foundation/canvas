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

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient
from logger import log

from photon_integration.client.photon_client import PhotonError
from photon_integration.patient_sync import build_client, resolve_photon_patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PhotonPrescribeModalAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the Photon Elements prescribe modal shell and assets."""

    PREFIX = "/photon"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [self._error_page("No patient was provided to the Photon modal.")]

        spa_client_id = (self.secrets.get("PHOTON_SPA_CLIENT_ID") or "").strip()
        org_id = (self.secrets.get("PHOTON_ORG_ID") or "").strip()
        if not spa_client_id or not org_id:
            return [
                self._error_page(
                    "Photon Elements is not configured "
                    "(PHOTON_SPA_CLIENT_ID / PHOTON_ORG_ID)."
                )
            ]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [self._error_page("Patient not found.")]

        effects: list[Response | Effect] = []
        try:
            photon_patient_id, ext_id_effect = resolve_photon_patient(
                patient, build_client(self.secrets)
            )
        except PhotonError as exc:
            log.error("Photon patient sync failed for %s: %s", patient_id, exc)
            return [self._error_page(f"Could not sync the patient to Photon: {exc}")]

        env = (self.secrets.get("PHOTON_ENV") or "sandbox").strip().lower()
        config = {
            "clientId": spa_client_id,
            "org": org_id,
            "patientId": photon_patient_id,
            "devMode": env != "production",
            "redirectUri": self._redirect_uri(),
        }
        html = render_to_string(
            "static/index.html",
            {"cache_bust": _CACHE_BUST, "config_json": json.dumps(config)},
        )
        if ext_id_effect is not None:
            effects.append(ext_id_effect)
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

    # -- helpers -----------------------------------------------------------

    def _redirect_uri(self) -> str:
        override = (self.secrets.get("PHOTON_REDIRECT_URI") or "").strip()
        if override:
            return override
        host = self.request.headers.get("host", "")
        return f"https://{host}/plugin-io/api/photon_integration/photon/"

    @staticmethod
    def _error_page(message: str) -> HTMLResponse:
        body = render_to_string("static/error.html", {"message": message})
        return HTMLResponse(body, status_code=HTTPStatus.OK, headers={"Cache-Control": "no-store"})
