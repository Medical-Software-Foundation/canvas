"""SimpleAPI endpoint serving the PayTheory hosted-fields card form.

Loaded in an iframe by the CardPaymentProcessor so each modal open gets a
fresh CustomElementRegistry (fixes KOALA-5882) and a real same-origin
origin (required by PayTheory's internal postMessage calls).
"""
from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string

from paytheory_payment_processor.paytheory.environment import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_PARTNER,
    get_sdk_url,
)


class CardFormAPI(SimpleAPI):
    """Serves the PayTheory hosted-fields card form as a standalone HTML page."""

    PREFIX = "/card-form"

    def authenticate(self, credentials: Credentials) -> bool:
        """The form only carries the PayTheory public key and tokenizes client-side."""
        return True

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        """Render the PayTheory hosted-fields form."""
        partner = self.secrets.get("paytheory_partner", DEFAULT_PARTNER)
        environment = self.secrets.get("paytheory_environment", DEFAULT_ENVIRONMENT)
        public_api_key = self.secrets["paytheory_public_key"]
        sdk_url = get_sdk_url(partner, environment)
        payor_id = self.query_params.get("payor_id", "")

        html = render_to_string(
            "templates/card_form.html",
            {"public_api_key": public_api_key, "sdk_url": sdk_url, "payor_id": payor_id},
        )
        return [
            HTMLResponse(
                content=html,
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-store"},
            )
        ]
